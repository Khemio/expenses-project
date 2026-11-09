import os

import psycopg
from dotenv import load_dotenv

from app.services.exceptions import BudgetConflict
from app.services.expense_workflow import process_expense

load_dotenv()


def get_current_budget_version(expense_id: int) -> int:
    """
    Read the current budget version for an expense.
    """
    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT b.version
                FROM expenses e
                JOIN budgets b ON e.budget_id = b.id
                WHERE e.id = %s
                """,
                (expense_id,),
            )

            row = cur.fetchone()

    if row is None:
        raise ValueError("Expense not found")

    return row[0]


def process_expense_with_retry(
    expense_id: int,
    approver_id: int,
    expected_version: int,
    max_attempts: int = 3,
):
    """
    Process an expense, retrying only budget-version conflicts.

    Every retry reenters process_expense(), which reloads
    the expense, checks its status, and verifies authorization.
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    version = expected_version

    for attempt in range(1, max_attempts + 1):
        try:
            return process_expense(
                expense_id=expense_id,
                approver_id=approver_id,
                expected_version=version,
            )

        except BudgetConflict:
            if attempt == max_attempts:
                raise

            version = get_current_budget_version(expense_id)

            print(
                f"Budget conflict on attempt {attempt}. "
                f"Retrying with version {version}."
            )