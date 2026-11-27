"""Persist the inputs used for a decision, not just its outcome."""
from decimal import Decimal

import pytest

from app.database.postgres import get_connection
from app.services.expense_workflow import approve_expense, escalate_expense


pytestmark = pytest.mark.integration


def test_approval_evidence_survives_later_budget_change(decision_scenario):
    s = decision_scenario
    result = approve_expense(
        expense_id=s["expense_id"],
        approver_id=s["approver_id"],
        expected_version=s["version"],
    )
    assert result["status"] == "approved"

    with get_connection() as conn:
        record = conn.execute(
            """
            SELECT id, created_at, decision, comment,
                   rule_version, evidence_snapshot
            FROM decisions
            WHERE expense_id = %s AND decision = 'approved'
            """,
            (s["expense_id"],),
        ).fetchone()

        assert record is not None
        decision_id, created_at, decision, comment, rule_version, evidence = record
        assert rule_version == "expense-workflow-v2"
        assert evidence["schema_version"] == 1
        assert Decimal(evidence["expense"]["amount"]) == Decimal("700")
        assert evidence["expense"]["status_before"] == "pending"
        assert evidence["expense"]["submitter_id"] == s["submitter_id"]
        assert evidence["budget"]["remaining_before"] == "2000.00"
        assert evidence["budget"]["remaining_after"] == "1300.00"
        assert evidence["budget"]["version_before"] == s["version"]
        assert evidence["budget"]["version_after"] == s["version"] + 1
        assert evidence["authorization"]["approver_authorized"] is True
        assert evidence["decision"]["outcome"] == "approved"

        # Later budget changes must not rewrite earlier decision evidence.
        conn.execute(
            """
            UPDATE budgets
            SET remaining = 900,
                version = version + 1
            WHERE id = %s
            """,
            (s["budget_id"],),
        )

        persisted = conn.execute(
            """
            SELECT evidence_snapshot
            FROM decisions
            WHERE expense_id = %s AND decision = 'approved'
            """,
            (s["expense_id"],),
        ).fetchone()[0]

    assert persisted == evidence
    assert persisted["budget"]["remaining_after"] == "1300.00"

    # Print saved, transactionally persisted values for Presentation II.
    # This is not a reconstruction from the current mutable budget.
    import json

    print("\nHISTORICAL DECISION EVIDENCE")
    print("  decision id:", decision_id)
    print("  decision timestamp:", created_at.isoformat())
    print("  outcome:", decision)
    print("  comment:", comment)
    print("  rule version:", rule_version)
    print("  source-backed evidence:")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    print("  current budget was changed to EUR 900 after approval")
    print("  retained original approved balance:", persisted["budget"]["remaining_after"])



def test_escalation_evidence_records_assigned_reviewer(decision_scenario):
    s = decision_scenario
    result = escalate_expense(
        expense_id=s["expense_id"],
        employee_id=s["submitter_id"],
        expected_version=s["version"],
    )
    assert result["status"] == "escalated"

    with get_connection() as conn:
        evidence = conn.execute(
            """
            SELECT evidence_snapshot
            FROM decisions
            WHERE expense_id = %s AND decision = 'escalated'
            """,
            (s["expense_id"],),
        ).fetchone()[0]

    assert evidence["authorization"]["target_approver_id"] == s["approver_id"]
    assert evidence["authorization"]["target_authorized"] is True
    assert evidence["budget"]["version_before"] == evidence["budget"]["version_after"]
    assert evidence["decision"]["reason_code"] == "ASSIGNED_AUTHORIZED_REVIEWER"
