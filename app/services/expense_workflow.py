import os

import psycopg
from dotenv import load_dotenv

from app.services.exceptions import BudgetConflict, WorkflowError
from app.services.authorization_service import is_authorized_approver
from app.services.escalation_service import find_responsible_approver

load_dotenv()


# class WorkflowError(Exception):
#     """Raised when an expense cannot be processed."""


def process_expense(
    expense_id: int,
    approver_id: int,
    expected_version: int,
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

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:

            # 1. Lock the expense against concurrent decisions.
            cur.execute(
                """
                SELECT
                    e.budget_id,
                    e.cost_centre_id,
                    e.amount,
                    e.expense_date,
                    e.status
                FROM expenses e
                WHERE e.id = %s
                FOR UPDATE OF e
                """,
                (expense_id,),
            )

            expense = cur.fetchone()

            if expense is None:
                raise WorkflowError("Expense not found")

            (
                budget_id,
                cost_centre_id,
                amount,
                expense_date,
                status,
            ) = expense

            if status not in ("pending", "escalated"):
                raise WorkflowError(
                    f"Expense cannot be processed: status={status}"
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
            authorized = is_authorized_approver(
                approver_id=approver_id,
                cost_centre_id=cost_centre_id,
                amount=amount,
                expense_date=expense_date,
            )

            # 4. An escalated expense must be handled by
            # the directly responsible employee.
            # if status == "escalated":
            #     responsible_id = find_responsible_approver(
            #         cost_centre_id
            #     )

            #     if (
            #         responsible_id != approver_id
            #         or not authorized
            #     ):
            #         raise WorkflowError(
            #             "Escalated expense requires its "
            #             "responsible approver"
            #         )
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

            # 5. Determine the business outcome.
            target_approver_id = None
            
            if authorized:
                if amount > remaining:
                    outcome = "rejected"
                    comment = "Rejected: insufficient budget"
                else:
                    outcome = "approved"
                    comment = "Approved by authorized employee"

            else:
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

                if amount > remaining:
                    raise WorkflowError(
                        "Insufficient budget; an authorized "
                        "approver must reject this expense"
                    )

                # outcome = "escalated"
                # comment = (
                #     f"Escalated to employee {responsible_id}"
                # )
                outcome = "escalated"
                target_approver_id = responsible_id
                comment = (
                    f"Escalated to employee {responsible_id}"
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
            # cur.execute(
            #     """
            #     INSERT INTO decisions (
            #         expense_id,
            #         approver_id,
            #         decision,
            #         comment
            #     )
            #     VALUES (%s, %s, %s, %s)
            #     """,
            #     (
            #         expense_id,
            #         approver_id,
            #         outcome,
            #         comment,
            #     ),
            # )
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
                    comment,
                ),
            )

        conn.commit()

    return {
        "expense_id": expense_id,
        "previous_status": status,
        "status": outcome,
        "approver_id": approver_id,
        "comment": comment,
    }