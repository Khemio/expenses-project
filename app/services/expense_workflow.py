
from typing import Literal

from psycopg.types.json import Jsonb

from app.services.exceptions import (
    BudgetConflict, 
    WorkflowError, 
    ExpenseNotFound,
    UnauthorizedApprover,
    SelfApprovalForbidden
)
from app.services.authorization_service import (
    is_authorized_approver,
    is_authorized_for_expense,
)
from app.services.escalation_service import find_responsible_approver
from app.services.reviewer_service import find_independent_reviewer
from app.database.postgres import get_connection

WorkflowAction = Literal[
    "approve",
    "reject",
    "escalate",
]

# Bump this when the decision rules change in a meaningful way.
RULE_VERSION = "expense-workflow-v1"


def process_expense(
    expense_id: int,
    approver_id: int,
    expected_version: int,
    action: WorkflowAction,
    comment: str | None = None,
):
    """
    Process an expense using PostgreSQL and Neo4j.

    Supported outcomes:
        approved
        rejected
        escalated

    An escalated expense may later be processed by the
    employee directly responsible for its cost centre.
    """

    if action not in ("approve", "reject", "escalate"):
        raise ValueError("Unsupported workflow action")
    
    with get_connection() as conn:
        with conn.cursor() as cur:

            # 1. Lock the expense against concurrent decisions.
            cur.execute(
                """
                SELECT
                    e.budget_id,
                    e.cost_centre_id,
                    e.amount,
                    e.expense_date,
                    e.status,
                    e.employee_id
                FROM expenses e
                WHERE e.id = %s
                FOR UPDATE OF e
                """,
                (expense_id,),
            )

            expense = cur.fetchone()

            if expense is None:
                raise ExpenseNotFound("Expense not found")

            (
                budget_id,
                cost_centre_id,
                amount,
                expense_date,
                status,
                submitter_id,
            ) = expense

            if status not in ("pending", "escalated"):
                raise WorkflowError(
                    f"Expense cannot be processed: status={status}"
                )
            

            if action in ("approve", "reject") and approver_id == submitter_id:
                raise SelfApprovalForbidden(
                    "Employees cannot approve or reject their own expenses"
                )


            # 2. Lock the budget and check its version.
            cur.execute(
                """
                SELECT remaining, version, cost_centre_id
                FROM budgets
                WHERE id = %s
                FOR UPDATE
                """,
                (budget_id,),
            )

            budget = cur.fetchone()

            if budget is None:
                raise WorkflowError("Budget not found")

            remaining, version, budget_cost_centre_id = budget

            if budget_cost_centre_id != cost_centre_id:
                raise WorkflowError(
                    "Expense and budget cost centres do not match"
                )

            if version != expected_version:
                raise BudgetConflict(
                    "Budget version changed; reload and reevaluate"
                )

            # 3. Check authority using the actual Neo4j graph.
                        
            if action in ("approve", "reject"):
                authorized = is_authorized_for_expense(
                    approver_id=approver_id,
                    submitter_id=submitter_id,
                    cost_centre_id=cost_centre_id,
                    amount=amount,
                    expense_date=expense_date,
                )
            else:
                authorized = is_authorized_approver(
                    approver_id=approver_id,
                    cost_centre_id=cost_centre_id,
                    amount=amount,
                    expense_date=expense_date,
                )


            # 4. An escalated expense must be handled by
            # the directly responsible employee.
            
            if status == "escalated":
                cur.execute(
                    """
                    SELECT target_approver_id
                    FROM decisions
                    WHERE expense_id = %s
                    AND decision = 'escalated'
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (expense_id,),
                )

                escalation = cur.fetchone()

                if escalation is None:
                    raise WorkflowError(
                        "Escalated expense has no escalation record"
                    )

                target_approver_id = escalation[0]

                if target_approver_id != approver_id:
                    raise WorkflowError(
                        f"Expense is assigned to employee "
                        f"{target_approver_id}, not {approver_id}"
                    )

                if not authorized:
                    raise WorkflowError(
                        "Assigned approver no longer has authority"
                    )

            
            # 5. Determine the requested outcome.
            target_approver_id = None
            target_authorized = None

            if action == "approve":
                if not authorized:
                    raise UnauthorizedApprover(
                        "Employee is not authorized to approve"
                    )

                if amount > remaining:
                    raise WorkflowError(
                        "Insufficient budget for approval"
                    )

                outcome = "approved"
                decision_comment = (
                    comment or "Approved by authorized employee"
                )

            elif action == "reject":
                if not authorized:
                    raise UnauthorizedApprover(
                        "Employee is not authorized to reject"
                    )

                outcome = "rejected"
                decision_comment = (
                    comment or "Rejected by authorized employee"
                )

            elif action == "escalate":
                if status != "pending":
                    raise WorkflowError(
                        "Only pending expenses may be escalated"
                    )

                # Initial policy: only the submitting employee
                # may explicitly request escalation.
                if approver_id != submitter_id:
                    raise UnauthorizedApprover(
                        "Only the submitter may request escalation"
                    )

                
                responsible_id = find_responsible_approver(
                    cost_centre_id
                )

                if responsible_id is None:
                    raise WorkflowError(
                        "No escalation target available"
                    )

                if responsible_id == submitter_id:
                    target_approver_id = find_independent_reviewer(
                        cost_centre_id=cost_centre_id,
                        submitter_id=submitter_id,
                    )
                else:
                    target_approver_id = responsible_id

                if target_approver_id is None:
                    raise WorkflowError(
                        "No independent reviewer configured"
                    )

                if target_approver_id == submitter_id:
                    raise WorkflowError(
                        "Cannot escalate an expense to its submitter"
                    )

                target_authorized = is_authorized_for_expense(
                    approver_id=target_approver_id,
                    submitter_id=submitter_id,
                    cost_centre_id=cost_centre_id,
                    amount=amount,
                    expense_date=expense_date,
                )

                if not target_authorized:
                    raise WorkflowError(
                        "Escalation target is not authorized"
                    )

                outcome = "escalated"
                decision_comment = (
                    comment
                    or f"Escalated to employee {target_approver_id}"
                )



            # 6. Deduct budget only for approval.
            if outcome == "approved":
                cur.execute(
                    """
                    UPDATE budgets
                    SET remaining = remaining - %s,
                        version = version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                      AND version = %s
                      AND remaining >= %s
                    RETURNING id
                    """,
                    (amount, budget_id, version, amount),
                )

                if cur.fetchone() is None:
                    raise BudgetConflict(
                        "Budget changed during approval"
                    )

            # 7. Update expense status.
            cur.execute(
                """
                UPDATE expenses
                SET status = %s
                WHERE id = %s
                  AND status = %s
                """,
                (outcome, expense_id, status),
            )

            if cur.rowcount != 1:
                raise WorkflowError(
                    "Expense status changed"
                )

            # 8. Capture the facts used by this decision *before* they
            # can be changed by later expenses or delegation updates.
            # JSON stores monetary values as strings to preserve Decimal precision.
            evidence_snapshot = {
                "schema_version": 1,
                "expense": {
                    "source_id": f"postgres:expenses:{expense_id}",
                    "submitter_id": submitter_id,
                    "cost_centre_id": cost_centre_id,
                    "budget_id": budget_id,
                    "amount": str(amount),
                    "expense_date": expense_date.isoformat(),
                    "status_before": status,
                },
                "budget": {
                    "source_id": f"postgres:budgets:{budget_id}",
                    "remaining_before": str(remaining),
                    "remaining_after": str(
                        remaining - amount if outcome == "approved" else remaining
                    ),
                    "version_before": version,
                    "version_after": version + (1 if outcome == "approved" else 0),
                },
                "authorization": {
                    "source": "neo4j",
                    "approver_id": approver_id,
                    "cost_centre_id": cost_centre_id,
                    "approver_authorized": (
                        bool(authorized) if action in ("approve", "reject") else None
                    ),
                    "target_approver_id": target_approver_id,
                    "target_authorized": target_authorized,
                    "max_delegation_hops": 5,
                },
                "decision": {
                    "requested_action": action,
                    "outcome": outcome,
                    "reason_code": {
                        "approve": "AUTHORIZED_WITH_SUFFICIENT_BUDGET",
                        "reject": "AUTHORIZED_EXPLICIT_REJECTION",
                        "escalate": "ASSIGNED_AUTHORIZED_REVIEWER",
                    }[action],
                },
            }

            # 9. Save the outcome and its evidence in the same
            # PostgreSQL transaction as the budget/status changes.
            cur.execute(
                """
                INSERT INTO decisions (
                    expense_id,
                    approver_id,
                    target_approver_id,
                    decision,
                    comment,
                    rule_version,
                    evidence_snapshot
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    expense_id,
                    approver_id,
                    target_approver_id,
                    outcome,
                    decision_comment,
                    RULE_VERSION,
                    Jsonb(evidence_snapshot),
                ),
            )

        conn.commit()

    return {
        "expense_id": expense_id,
        "previous_status": status,
        "status": outcome,
        "approver_id": approver_id,
        "comment": decision_comment,
    }



def approve_expense(
    expense_id: int,
    approver_id: int,
    expected_version: int,
):
    return process_expense(
        expense_id=expense_id,
        approver_id=approver_id,
        expected_version=expected_version,
        action="approve",
    )


def reject_expense(
    expense_id: int,
    approver_id: int,
    expected_version: int,
    reason: str,
):
    if not reason.strip():
        raise ValueError("Rejection reason cannot be blank")

    return process_expense(
        expense_id=expense_id,
        approver_id=approver_id,
        expected_version=expected_version,
        action="reject",
        comment=reason.strip(),
    )


def escalate_expense(
    expense_id: int,
    employee_id: int,
    expected_version: int,
):
    return process_expense(
        expense_id=expense_id,
        approver_id=employee_id,
        expected_version=expected_version,
        action="escalate",
    )
