import os
import psycopg
from dotenv import load_dotenv

from app.services.exceptions import BudgetConflict

load_dotenv()


# class BudgetConflict(Exception):
#     """Raised when the budget has changed or has insufficient funds."""
#     pass


def approve_expense(
    expense_id: int,
    approver_id: int,
    expected_version: int,
):
    with psycopg.connect(
        host="localhost",
        port=5432,
        dbname="expense_approval",
        user="expense_user",
        password=os.getenv("POSTGRES_PASSWORD"),
    ) as conn:
        with conn.cursor() as cur:

            # 1. Load the expense
            cur.execute(
                """
                SELECT budget_id, amount, status
                FROM expenses
                WHERE id = %s
                """,
                (expense_id,),
            )

            expense = cur.fetchone()

            if expense is None:
                raise ValueError("Expense not found")

            budget_id, amount, status = expense

            if status != "pending":
                raise ValueError("Expense is not pending")

            # 2. Atomically update the budget.
            # Only succeeds if the version is unchanged
            # and enough money remains.
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
                (amount, budget_id, expected_version, amount),
            )

            if cur.fetchone() is None:
                raise BudgetConflict(
                    "Budget changed or insufficient remaining balance"
                )

            # 3. Mark the expense as approved
            cur.execute(
                """
                UPDATE expenses
                SET status = 'approved'
                WHERE id = %s AND status = 'pending'
                """,
                (expense_id,),
            )

            if cur.rowcount != 1:
                raise ValueError("Expense status changed")

            # 4. Record the decision
            cur.execute(
                """
                INSERT INTO decisions (
                    expense_id, approver_id, decision
                )
                VALUES (%s, %s, 'approved')
                """,
                (expense_id, approver_id),
            )

    return f"Expense {expense_id} approved successfully"
