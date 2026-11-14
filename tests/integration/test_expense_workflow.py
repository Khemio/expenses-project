
from decimal import Decimal

import pytest

from app.database.postgres import get_connection
from app.services.exceptions import WorkflowError
from app.services.expense_workflow import process_expense
from app.services.exceptions import BudgetConflict, WorkflowError


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


@pytest.mark.integration
def test_rejection_for_insufficient_budget(expense_scenario):
    expense_id = expense_scenario["expense_id"]
    approver_id = expense_scenario["employee_id"]
    budget_id = expense_scenario["budget_id"]
    initial_version = expense_scenario["version"]

    # Increase the expense amount beyond the available budget.
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE expenses
            SET amount = 2500
            WHERE id = %s
            """,
            (expense_id,),
        )

    result = process_expense(
        expense_id=expense_id,
        approver_id=approver_id,
        expected_version=initial_version,
    )

    assert result["status"] == "rejected"
    assert result["previous_status"] == "pending"

    with get_connection() as conn:
        budget = conn.execute(
            """
            SELECT remaining, version
            FROM budgets
            WHERE id = %s
            """,
            (budget_id,),
        ).fetchone()

        expense_status = conn.execute(
            """
            SELECT status
            FROM expenses
            WHERE id = %s
            """,
            (expense_id,),
        ).fetchone()[0]

        decisions = conn.execute(
            """
            SELECT decision, approver_id
            FROM decisions
            WHERE expense_id = %s
            """,
            (expense_id,),
        ).fetchall()

    assert budget == (
        Decimal("2000"),
        initial_version,
    )
    assert expense_status == "rejected"
    assert decisions == [("rejected", approver_id)]


@pytest.mark.integration
def test_stale_budget_version_blocks_approval(expense_scenario):
    expense_id = expense_scenario["expense_id"]
    approver_id = expense_scenario["employee_id"]
    budget_id = expense_scenario["budget_id"]
    initial_version = expense_scenario["version"]

    # Simulate a concurrent budget modification.
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE budgets
            SET version = version + 1
            WHERE id = %s
            """,
            (budget_id,),
        )

    with pytest.raises(BudgetConflict):
        process_expense(
            expense_id=expense_id,
            approver_id=approver_id,
            expected_version=initial_version,
        )

    # A version conflict must not modify the expense.
    with get_connection() as conn:
        budget = conn.execute(
            """
            SELECT remaining, version
            FROM budgets
            WHERE id = %s
            """,
            (budget_id,),
        ).fetchone()

        expense_status = conn.execute(
            """
            SELECT status
            FROM expenses
            WHERE id = %s
            """,
            (expense_id,),
        ).fetchone()[0]

        decision_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM decisions
            WHERE expense_id = %s
            """,
            (expense_id,),
        ).fetchone()[0]

    assert budget == (
        Decimal("2000"),
        initial_version + 1,
    )
    assert expense_status == "pending"
    assert decision_count == 0

