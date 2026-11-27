
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from datetime import date

import pytest

from app.database.postgres import get_connection
from app.services.exceptions import BudgetConflict, WorkflowError
from app.services.expense_workflow import approve_expense


def attempt_approval(expense_id, approver_id, version, start_event):
    start_event.wait()

    try:
        result = approve_expense(
            expense_id=expense_id,
            approver_id=approver_id,
            expected_version=version,
        )
        return ("success", result)

    except (WorkflowError, BudgetConflict) as error:
        return ("blocked", str(error))


@pytest.mark.integration
def test_concurrent_approval_of_same_expense(decision_scenario):
    expense_id = decision_scenario["expense_id"]
    approver_id = decision_scenario["employee_id"]
    budget_id = decision_scenario["budget_id"]
    initial_version = decision_scenario["version"]

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



def attempt_shared_budget_approval(
    expense_id,
    approver_id,
    version,
    start_event,
):
    start_event.wait()

    try:
        result = approve_expense(
            expense_id=expense_id,
            approver_id=approver_id,
            expected_version=version,
        )
        return ("success", expense_id, result)

    except BudgetConflict as error:
        return ("conflict", expense_id, str(error))


@pytest.mark.integration
def test_concurrent_expenses_sharing_budget(decision_scenario):
    first_expense_id = decision_scenario["expense_id"]
    employee_id = decision_scenario["employee_id"]
    cost_centre_id = decision_scenario["cost_centre_id"]
    budget_id = decision_scenario["budget_id"]
    initial_version = decision_scenario["version"]

    second_expense_id = decision_scenario["create_expense"](
        amount=700,
        description="Second concurrent expense",
        employee_id=decision_scenario["submitter_id"],
    )


    with get_connection() as conn:
        conn.execute(
            """
            UPDATE budgets
            SET total = 1000, remaining = 1000
            WHERE id = %s
            """,
            (budget_id,),
        )


    start_event = Event()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                attempt_shared_budget_approval,
                expense_id,
                employee_id,
                initial_version,
                start_event,
            )
            for expense_id in (
                first_expense_id,
                second_expense_id,
            )
        ]

        start_event.set()
        results = [future.result() for future in futures]

    successes = [r for r in results if r[0] == "success"]
    conflicts = [r for r in results if r[0] == "conflict"]

    assert len(successes) == 1
    assert len(conflicts) == 1

    winner_id = successes[0][1]

    with get_connection() as conn:
        budget = conn.execute(
            """
            SELECT remaining, version
            FROM budgets
            WHERE id = %s
            """,
            (budget_id,),
        ).fetchone()

        expense_states = conn.execute(
            """
            SELECT id, status
            FROM expenses
            WHERE id = ANY(%s)
            ORDER BY id
            """,
            ([first_expense_id, second_expense_id],),
        ).fetchall()

        decisions = conn.execute(
            """
            SELECT expense_id, decision, approver_id
            FROM decisions
            WHERE expense_id = ANY(%s)
            """,
            ([first_expense_id, second_expense_id],),
        ).fetchall()

    assert budget == (
        Decimal("300"),
        initial_version + 1,
    )

    statuses = dict(expense_states)

    assert statuses[winner_id] == "approved"
    assert list(statuses.values()).count("pending") == 1

    assert decisions == [
        (winner_id, "approved", employee_id),
    ]

    print("\nTWO EXPENSES / ONE SHARED BUDGET")
    print("  submitted amounts: EUR 700 + EUR 700")
    print("  starting budget: EUR 1000")
    print("  committed approvals:", len(successes))
    print("  version conflicts:", len(conflicts))
    print("  budget remaining:", budget[0])
    print("  budget version:", budget[1])
    print("  decisions recorded:", len(decisions))
