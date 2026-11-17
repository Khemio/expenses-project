
from psycopg.rows import dict_row

from app.database.postgres import get_connection


def get_expense(
    expense_id: int,
    employee_id: int,
) -> dict | None:
    """Retrieve an expense owned by an employee."""

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
                  AND employee_id = %s
                """,
                (expense_id, employee_id),
            )

            return cur.fetchone()


def list_expenses(
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    cost_centre_id: int | None = None,
    employee_id: int,
) -> dict:
    conditions = ["employee_id = %s"]
    params = [employee_id]

    if status is not None:
        conditions.append("status = %s")
        params.append(status)

    if cost_centre_id is not None:
        conditions.append("cost_centre_id = %s")
        params.append(cost_centre_id)

    where = (
        "WHERE " + " AND ".join(conditions)
        if conditions
        else ""
    )

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT COUNT(*) AS total FROM expenses {where}",
                params,
            )
            total = cur.fetchone()["total"]

            cur.execute(
                f"""
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
                {where}
                ORDER BY id DESC
                LIMIT %s OFFSET %s
                """,
                [*params, limit, offset],
            )
            items = cur.fetchall()

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
