
from datetime import date
from decimal import Decimal

from psycopg.rows import dict_row

from app.database.postgres import get_connection


class InvalidExpenseAssignment(Exception):
    """Employee, cost centre, or budget association is invalid."""


def submit_expense(
    *,
    employee_id: int,
    cost_centre_id: int,
    budget_id: int,
    amount: Decimal,
    description: str,
    expense_date: date,
) -> dict:
    """Create a pending expense using validated associations."""

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO expenses (
                    employee_id,
                    cost_centre_id,
                    budget_id,
                    amount,
                    description,
                    expense_date
                )
                SELECT
                    e.id,
                    e.cost_centre_id,
                    b.id,
                    %s,
                    %s,
                    %s
                FROM employees AS e
                JOIN budgets AS b
                    ON b.cost_centre_id = e.cost_centre_id
                WHERE e.id = %s
                  AND e.cost_centre_id = %s
                  AND b.id = %s
                RETURNING
                    id,
                    employee_id,
                    cost_centre_id,
                    budget_id,
                    amount,
                    description,
                    expense_date,
                    status,
                    created_at
                """,
                (
                    amount,
                    description,
                    expense_date,
                    employee_id,
                    cost_centre_id,
                    budget_id,
                ),
            )

            expense = cur.fetchone()

            if expense is None:
                raise InvalidExpenseAssignment(
                    "Invalid employee, cost centre, "
                    "or budget association"
                )

            return expense
