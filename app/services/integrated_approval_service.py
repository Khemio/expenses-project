import os

import psycopg
from dotenv import load_dotenv

from app.services.approval_service import approve_expense
from app.services.authorization_service import is_authorized_approver

load_dotenv()


class UnauthorizedApprover(Exception):
    """Raised when an employee lacks approval authority."""
    pass


def approve_expense_with_authorization(
    expense_id: int,
    approver_id: int,
    expected_version: int,
):
    # 1. Load the expense information from PostgreSQL.
    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    cost_centre_id,
                    amount,
                    expense_date,
                    status
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
        raise ValueError("Expense is not pending")

    # 2. Ask Neo4j whether the approver is authorized.
    authorized = is_authorized_approver(
        approver_id=approver_id,
        cost_centre_id=cost_centre_id,
        amount=amount,
        expense_date=expense_date,
    )

    if not authorized:
        raise UnauthorizedApprover(
            f"Employee {approver_id} is not authorized "
            f"to approve expense {expense_id}"
        )

    # 3. Delegate the budget update and decision recording
    # to the existing PostgreSQL approval service.
    return approve_expense(
        expense_id=expense_id,
        approver_id=approver_id,
        expected_version=expected_version,
    )