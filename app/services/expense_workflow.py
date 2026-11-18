
from typing import Literal

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
from app.database.postgres import get_connection

WorkflowAction = Literal[
    "approve",
    "reject",
    "escalate",
]


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

            # if action not in (
            #     "automatic", "approve", "reject", "escalate"
            # ):
            #     raise ValueError("Unsupported workflow action")

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

                target_authorized = is_authorized_approver(
                    approver_id=responsible_id,
                    cost_centre_id=cost_centre_id,
                    amount=amount,
                    expense_date=expense_date,
                )

                if not target_authorized:
                    raise WorkflowError(
                        "Escalation target is not authorized"
                    )

                outcome = "escalated"
                target_approver_id = responsible_id
                decision_comment = (
                    comment
                    or f"Escalated to employee {responsible_id}"
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

            # 8. Record the decision.
            cur.execute(
                """
                INSERT INTO decisions (
                    expense_id,
                    approver_id,
                    target_approver_id,
                    decision,
                    comment
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    expense_id,
                    approver_id,
                    target_approver_id,
                    outcome,
                    decision_comment,
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
