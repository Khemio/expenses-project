
import pytest

from app.database.postgres import get_connection


pytestmark = pytest.mark.integration


def test_factory_allows_explicit_submitter(expense_scenario):
    s = expense_scenario

    expense_id = s["create_expense"](
        amount=125,
        description="Alternate submitter",
        employee_id=s["unauthorized_employee_id"],
    )

    with get_connection() as conn:
        employee_id = conn.execute(
            """
            SELECT employee_id
            FROM expenses
            WHERE id = %s
            """,
            (expense_id,),
        ).fetchone()[0]

    assert employee_id == s["unauthorized_employee_id"]


def test_factory_preserves_default_employee(expense_scenario):
    s = expense_scenario

    expense_id = s["create_expense"](
        amount=125,
        description="Default submitter",
    )

    with get_connection() as conn:
        employee_id = conn.execute(
            """
            SELECT employee_id
            FROM expenses
            WHERE id = %s
            """,
            (expense_id,),
        ).fetchone()[0]

    assert employee_id == s["employee_id"]
