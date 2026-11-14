
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event

import pytest

from app.database.postgres import get_connection
from app.services.exceptions import BudgetConflict, WorkflowError
from app.services.expense_workflow import process_expense


def attempt_approval(expense_id, approver_id, version, start_event):
    start_event.wait()

    try:
        result = process_expense(
            expense_id=expense_id,
            approver_id=approver_id,
            expected_version=version,
        )
        return ("success", result)

    except (WorkflowError, BudgetConflict) as error:
        return ("blocked", str(error))


@pytest.mark.integration
def test_concurrent_approval_of_same_expense(expense_scenario):
    expense_id = expense_scenario["expense_id"]
    approver_id = expense_scenario["employee_id"]
    budget_id = expense_scenario["budget_id"]
    initial_version = expense_scenario["version"]

    start_event = Event()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                attempt_approval,
                expense_id,
                approver_id,
                initial_version,
                start_event,
            )
            for _ in range(2)
        ]

        # Release both workers to attempt approval.
        start_event.set()

        results = [future.result() for future in futures]

    successes = [r for r in results if r[0] == "success"]
    blocked = [r for r in results if r[0] == "blocked"]

    assert len(successes) == 1
    assert len(blocked) == 1
    assert successes[0][1]["status"] == "approved"

    # Verify persisted state, not just return values.
    with get_connection() as conn:
        budget = conn.execute(
            """
            SELECT remaining, version
            FROM budgets
            WHERE id = %s
            """,
            (budget_id,),
        ).fetchone()

        status = conn.execute(
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
        Decimal("1300"),
        initial_version + 1,
    )
    assert status == "approved"
    assert decisions == [
        ("approved", approver_id),
    ]
