
from decimal import Decimal

import pytest

from app.database.postgres import get_connection
from app.services.exceptions import (
    UnauthorizedApprover,
    WorkflowError,
)
from app.services.expense_workflow import (
    approve_expense,
    reject_expense,
    escalate_expense,
)


pytestmark = pytest.mark.integration


def get_state(expense_id, budget_id):
    """Inspect persisted workflow and budget state."""
    with get_connection() as conn:
        expense = conn.execute(
            """
            SELECT status FROM expenses
            WHERE id = %s
            """,
            (expense_id,),
        ).fetchone()[0]

        budget = conn.execute(
            """
            SELECT remaining, version FROM budgets
            WHERE id = %s
            """,
            (budget_id,),
        ).fetchone()

        decisions = conn.execute(
            """
            SELECT decision, approver_id,
                   target_approver_id, comment
            FROM decisions
            WHERE expense_id = %s
            ORDER BY id
            """,
            (expense_id,),
        ).fetchall()

    return expense, budget, decisions


def test_explicit_approval(decision_scenario):
    s = decision_scenario

    result = approve_expense(
        expense_id=s["expense_id"],
        approver_id=s["employee_id"],
        expected_version=s["version"],
    )

    assert result["status"] == "approved"

    status, budget, decisions = get_state(
        s["expense_id"], s["budget_id"]
    )

    assert status == "approved"
    assert budget == (
        Decimal("1300"),
        s["version"] + 1,
    )
    assert len(decisions) == 1
    assert decisions[0][0] == "approved"
    assert decisions[0][1] == s["employee_id"]


def test_unauthorized_approval_does_not_escalate(
    expense_scenario,
):
    s = expense_scenario

    with pytest.raises(UnauthorizedApprover):
        approve_expense(
            expense_id=s["expense_id"],
            approver_id=s["unauthorized_employee_id"],
            expected_version=s["version"],
        )

    status, budget, decisions = get_state(
        s["expense_id"], s["budget_id"]
    )

    assert status == "pending"
    assert budget == (
        Decimal("2000"),
        s["version"],
    )
    assert decisions == []


def test_explicit_rejection_preserves_budget(
    decision_scenario,
):
    s = decision_scenario

    result = reject_expense(
        expense_id=s["expense_id"],
        approver_id=s["employee_id"],
        expected_version=s["version"],
        reason="Receipt does not match the request",
    )

    assert result["status"] == "rejected"

    status, budget, decisions = get_state(
        s["expense_id"], s["budget_id"]
    )

    assert status == "rejected"
    assert budget == (
        Decimal("2000"),
        s["version"],
    )
    assert len(decisions) == 1
    assert decisions[0][3] == (
        "Receipt does not match the request"
    )


def test_unauthorized_rejection(expense_scenario):
    s = expense_scenario

    with pytest.raises(UnauthorizedApprover):
        reject_expense(
            expense_id=s["expense_id"],
            approver_id=s["unauthorized_employee_id"],
            expected_version=s["version"],
            reason="Not approved",
        )

    status, _, decisions = get_state(
        s["expense_id"], s["budget_id"]
    )

    assert status == "pending"
    assert decisions == []


def test_submitter_can_explicitly_escalate(
    decision_scenario,
):
    s = decision_scenario

    result = escalate_expense(
        expense_id=s["expense_id"],
        employee_id=s["submitter_id"],
        expected_version=s["version"],
    )

    assert result["status"] == "escalated"

    status, budget, decisions = get_state(
        s["expense_id"], s["budget_id"]
    )

    assert status == "escalated"
    assert budget == (
        Decimal("2000"),
        s["version"],
    )
    assert len(decisions) == 1
    assert decisions[0][0] == "escalated"
    assert decisions[0][2] == s["employee_id"]

    # The assigned approver completes the escalation.
    result = approve_expense(
        expense_id=s["expense_id"],
        approver_id=s["employee_id"],
        expected_version=s["version"],
    )

    assert result["status"] == "approved"


def test_non_submitter_cannot_escalate(
    expense_scenario,
):
    s = expense_scenario

    with pytest.raises(UnauthorizedApprover):
        escalate_expense(
            expense_id=s["expense_id"],
            employee_id=s["unauthorized_employee_id"],
            expected_version=s["version"],
        )

    status, _, decisions = get_state(
        s["expense_id"], s["budget_id"]
    )

    assert status == "pending"
    assert decisions == []


def test_approval_with_insufficient_budget(
    decision_scenario,
):
    s = decision_scenario

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE expenses SET amount = 2500
            WHERE id = %s
            """,
            (s["expense_id"],),
        )

    with pytest.raises(
        WorkflowError,
        match="Insufficient budget",
    ):
        approve_expense(
            expense_id=s["expense_id"],
            approver_id=s["approver_id"],
            expected_version=s["version"],
        )

    status, budget, decisions = get_state(
        s["expense_id"], s["budget_id"]
    )

    assert status == "pending"
    assert budget == (
        Decimal("2000"),
        s["version"],
    )
    assert decisions == []
