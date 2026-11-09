import os

import psycopg
from dotenv import load_dotenv

from app.services.exceptions import BudgetConflict
from app.services.authorization_service import is_authorized_approver

load_dotenv()


class RejectionError(Exception):
    """Raised when the requested rejection is not valid."""
    pass


def reject_expense_for_insufficient_budget(
    expense_id: int,
    approver_id: int,
    expected_version: int,
):
    """
    Reject a pending expense when its amount exceeds the budget.

    The budget balance and version remain unchanged.
    """

    # Read the information needed for authorization.
    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cost_centre_id, amount, expense_date, status
                FROM expenses
                WHERE id = %s
                """,
                (expense_id,),
            )

            expense = cur.fetchone()

    if expense is None:
        raise ValueError("Expense not found")

    cost_centre_id, amount, expense_date, status = expense

    if status != "pending":
        raise RejectionError("Expense is not pending")

    # Require a valid approver for this decision.
    authorized = is_authorized_approver(
        approver_id=approver_id,
        cost_centre_id=cost_centre_id,
        amount=amount,
        expense_date=expense_date,
    )

    if not authorized:
        raise RejectionError("Approver is not authorized")

    # Record the rejection atomically in PostgreSQL.
    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT budget_id, amount, status
                FROM expenses
                WHERE id = %s
                FOR UPDATE
                """,
                (expense_id,),
            )

            locked_expense = cur.fetchone()

            if locked_expense is None:
                raise ValueError("Expense not found")

            budget_id, locked_amount, locked_status = locked_expense

            if locked_status != "pending":
                raise RejectionError("Expense status changed")

            cur.execute(
                """
                SELECT remaining, version
                FROM budgets
                WHERE id = %s
                FOR UPDATE
                """,
                (budget_id,),
            )

            budget = cur.fetchone()

            if budget is None:
                raise ValueError("Budget not found")

            remaining, version = budget

            if version != expected_version:
                raise BudgetConflict(
                    "Budget version changed; reevaluate expense"
                )

            if locked_amount <= remaining:
                raise RejectionError(
                    "Budget is sufficient; rejection reason is invalid"
                )

            cur.execute(
                """
                UPDATE expenses
                SET status = 'rejected'
                WHERE id = %s AND status = 'pending'
                """,
                (expense_id,),
            )

            if cur.rowcount != 1:
                raise RejectionError("Expense status changed")

            cur.execute(
                """
                INSERT INTO decisions (
                    expense_id,
                    approver_id,
                    decision,
                    comment
                )
                VALUES (%s, %s, 'rejected', %s)
                """,
                (
                    expense_id,
                    approver_id,
                    "Rejected: insufficient remaining budget",
                ),
            )

        conn.commit()

    return {
        "expense_id": expense_id,
        "status": "rejected",
        "reason": "insufficient_budget",
    }