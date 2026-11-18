
from datetime import date

from app.database.postgres import get_connection


class ExpenseFactory:
    """Create and track expenses for integration tests."""

    def __init__(
        self,
        employee_id: int,
        cost_centre_id: int,
        budget_id: int,
    ):
        self.employee_id = employee_id
        self.cost_centre_id = cost_centre_id
        self.budget_id = budget_id
        self.expense_ids: list[int] = []

    def track(self, expense_id: int) -> None:
        """Register an expense for eventual cleanup."""
        self.expense_ids.append(expense_id)

    def create(
        self,
        amount=700,
        description="Integration test expense",
        expense_date=date(2026, 11, 9),
        employee_id: int | None = None,
    ) -> int:
        """Create another expense using the scenario's budget."""

        with get_connection() as conn:
            with conn.cursor() as cur:
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
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        self.employee_id if employee_id is None else employee_id,
                        self.cost_centre_id,
                        self.budget_id,
                        amount,
                        description,
                        expense_date,
                    ),
                )

                expense_id = cur.fetchone()[0]

        self.track(expense_id)
        return expense_id

    def cleanup(self, cursor) -> None:
        """Delete tracked expenses and their decisions.

        Uses the caller's existing transaction.
        """

        if not self.expense_ids:
            return

        cursor.execute(
            """
            DELETE FROM decisions
            WHERE expense_id = ANY(%s)
            """,
            (self.expense_ids,),
        )

        cursor.execute(
            """
            DELETE FROM expenses
            WHERE id = ANY(%s)
            """,
            (self.expense_ids,),
        )
