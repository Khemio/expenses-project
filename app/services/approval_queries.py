
from psycopg.rows import dict_row

from app.database.postgres import get_connection
from app.services.authorization_service import (
    is_authorized_approver,
)


def list_actionable_expenses(
    *,
    approver_id: int,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List expenses currently actionable by an approver.

    Authorization is evaluated before pagination.
    """

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    e.id,
                    e.employee_id,
                    e.cost_centre_id,
                    e.budget_id,
                    e.amount,
                    e.description,
                    e.expense_date,
                    e.status,
                    e.created_at,
                    b.version AS budget_version
                FROM expenses AS e
                JOIN budgets AS b ON b.id = e.budget_id
                LEFT JOIN LATERAL (
                    SELECT d.target_approver_id
                    FROM decisions AS d
                    WHERE d.expense_id = e.id
                      AND d.decision = 'escalated'
                    ORDER BY d.id DESC
                    LIMIT 1
                ) AS assignment ON TRUE
                WHERE e.status = 'pending'
                   OR (
                       e.status = 'escalated'
                       AND assignment.target_approver_id = %s
                   )
                ORDER BY e.id DESC
                """,
                (approver_id,),
            )

            candidates = cur.fetchall()

    # Filter all candidates before calculating page totals.
    authorized = []

    for expense in candidates:
        if is_authorized_approver(
            approver_id=approver_id,
            cost_centre_id=expense["cost_centre_id"],
            amount=expense["amount"],
            expense_date=expense["expense_date"],
        ):
            authorized.append(expense)

    return {
        "items": authorized[offset:offset + limit],
        "total": len(authorized),
        "limit": limit,
        "offset": offset,
    }
