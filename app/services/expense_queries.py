
from psycopg.rows import dict_row

from app.database.postgres import get_connection

def get_expense(expense_id: int) -> dict | None:
    """Retrieve one expense without modifying database state."""

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    employee_id,
                    cost_centre_id,
                    budget_id,
                    amount,
                    description,
                    expense_date,
                    status,
                    created_at
                FROM expenses
                WHERE id = %s
                """,
                (expense_id,),
            )

            return cur.fetchone()