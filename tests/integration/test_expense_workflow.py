
from decimal import Decimal

import pytest

from app.database.postgres import get_connection
from app.services.exceptions import WorkflowError
from app.services.expense_workflow import process_expense


@pytest.mark.integration
def test_approval_and_duplicate_prevention(expense_scenario):
    expense_id = expense_scenario["expense_id"]
    approver_id = expense_scenario["employee_id"]
    budget_id = expense_scenario["budget_id"]
    initial_version = expense_scenario["version"]

    # First approval should succeed.
    result = process_expense(
        expense_id=expense_id,
        approver_id=approver_id,
        expected_version=initial_version,
    )

    assert result["status"] == "approved"
    assert result["previous_status"] == "pending"
    assert result["approver_id"] == approver_id

    # Verify the actual PostgreSQL state.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT remaining, version
                FROM budgets
                WHERE id = %s
                """,
                (budget_id,),
            )
            remaining, version = cur.fetchone()

            cur.execute(
                """
                SELECT status
                FROM expenses
                WHERE id = %s
                """,
                (expense_id,),
            )
            status = cur.fetchone()[0]

            cur.execute(
                """
                SELECT decision, approver_id
                FROM decisions
                WHERE expense_id = %s
                """,
                (expense_id,),
            )
            decisions = cur.fetchall()

    assert remaining == Decimal("1300")
    assert version == initial_version + 1
    assert status == "approved"
    assert decisions == [("approved", approver_id)]

    # Repeated approval must fail.
    with pytest.raises(WorkflowError):
        process_expense(
            expense_id=expense_id,
            approver_id=approver_id,
            expected_version=version,
        )

    # Failed approval must not alter persisted state.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT remaining, version
                FROM budgets
                WHERE id = %s
                """,
                (budget_id,),
            )
            assert cur.fetchone() == (
                Decimal("1300"),
                initial_version + 1,
            )

            cur.execute(
                """
                SELECT COUNT(*)
                FROM decisions
                WHERE expense_id = %s
                """,
                (expense_id,),
            )
            assert cur.fetchone()[0] == 1
