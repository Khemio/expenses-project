
from decimal import Decimal

import pytest

from app.database.postgres import get_connection
from app.services.expense_workflow import (
    approve_expense,
    escalate_expense,
)
from app.services.exceptions import (
    UnauthorizedApprover,
)


pytestmark = pytest.mark.integration


@pytest.fixture
def handoff_expense(expense_scenario):
    s = expense_scenario

    with get_connection() as conn:
        expense_id = conn.execute(
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
                s["unauthorized_employee_id"],
                s["cost_centre_id"],
                s["budget_id"],
                Decimal("350.00"),
                "Approval handoff test",
                "2026-11-17",
            ),
        ).fetchone()[0]

    s["track_expense"](expense_id)
    return expense_id


def test_submitter_cannot_approve_own_expense(
    expense_scenario,
    handoff_expense,
):
    s = expense_scenario

    with pytest.raises(UnauthorizedApprover):
        approve_expense(
            expense_id=handoff_expense,
            approver_id=s["unauthorized_employee_id"],
            expected_version=s["version"],
        )


def test_responsible_employee_can_approve(
    expense_scenario,
    handoff_expense,
):
    s = expense_scenario

    result = approve_expense(
        expense_id=handoff_expense,
        approver_id=s["employee_id"],
        expected_version=s["version"],
    )

    assert result["status"] == "approved"

    with get_connection() as conn:
        budget = conn.execute(
            """
            SELECT remaining, version
            FROM budgets
            WHERE id = %s
            """,
            (s["budget_id"],),
        ).fetchone()

    assert budget == (
        Decimal("1650.00"),
        s["version"] + 1,
    )


def test_escalation_handoff(
    expense_scenario,
    handoff_expense,
):
    s = expense_scenario
    submitter_id = s["unauthorized_employee_id"]
    approver_id = s["employee_id"]

    result = escalate_expense(
        expense_id=handoff_expense,
        employee_id=submitter_id,
        expected_version=s["version"],
    )

    assert result["status"] == "escalated"

    with get_connection() as conn:
        decision = conn.execute(
            """
            SELECT approver_id, target_approver_id
            FROM decisions
            WHERE expense_id = %s
              AND decision = 'escalated'
            ORDER BY id DESC
            LIMIT 1
            """,
            (handoff_expense,),
        ).fetchone()

    assert decision == (submitter_id, approver_id)

    result = approve_expense(
        expense_id=handoff_expense,
        approver_id=approver_id,
        expected_version=s["version"],
    )

    assert result["status"] == "approved"
    assert result["previous_status"] == "escalated"
