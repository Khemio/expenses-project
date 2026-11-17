
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

def test_submitter_cannot_approve_own_expense(
    approval_handoff_scenario,
):
    s = approval_handoff_scenario

    with pytest.raises(UnauthorizedApprover):
        approve_expense(
            expense_id=s['expense_id'],
            approver_id=s["submitter_id"],
            expected_version=s["version"],
        )



@pytest.mark.integration
def test_responsible_employee_can_approve(
    approval_handoff_scenario,
):
    s = approval_handoff_scenario

    result = approve_expense(
        expense_id=s["expense_id"],
        approver_id=s["approver_id"],
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
    approval_handoff_scenario,
):
    s = approval_handoff_scenario

    submitter_id = s["submitter_id"]
    approver_id = s["approver_id"]
    expense_id = s['expense_id']
    result = escalate_expense(
        expense_id=expense_id,
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
            (expense_id,),
        ).fetchone()

    assert decision == (submitter_id, approver_id)

    result = approve_expense(
        expense_id=expense_id,
        approver_id=approver_id,
        expected_version=s["version"],
    )

    assert result["status"] == "approved"
    assert result["previous_status"] == "escalated"
