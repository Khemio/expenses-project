"""The approval path must not silently proceed with absent receipt evidence."""

from decimal import Decimal

import pytest
from bson.decimal128 import Decimal128
from pymongo import MongoClient

from app.config import get_settings
from app.database.postgres import get_connection
from app.services.exceptions import MissingReceiptEvidence, ReceiptEvidenceUnavailable
import app.services.expense_workflow as workflow
from app.services.expense_workflow import approve_expense, reject_expense

pytestmark = pytest.mark.integration


def _receipt_collection():
    client = MongoClient(get_settings().mongo_uri)
    return client, client["expense_approval"]["receipts"]


def _assert_unchanged(s):
    with get_connection() as conn:
        assert conn.execute(
            "SELECT status FROM expenses WHERE id = %s",
            (s["expense_id"],),
        ).fetchone()[0] == "pending"
        assert conn.execute(
            "SELECT remaining, version FROM budgets WHERE id = %s",
            (s["budget_id"],),
        ).fetchone() == (Decimal("2000"), s["version"])
        assert conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE expense_id = %s",
            (s["expense_id"],),
        ).fetchone()[0] == 0


def test_missing_receipt_blocks_approval(decision_scenario):
    s = decision_scenario
    client, receipts = _receipt_collection()
    try:
        receipts.delete_many({"expense_id": s["expense_id"]})
    finally:
        client.close()

    with pytest.raises(MissingReceiptEvidence, match="No receipt"):
        approve_expense(
            expense_id=s["expense_id"],
            approver_id=s["approver_id"],
            expected_version=s["version"],
        )

    _assert_unchanged(s)


def test_wrong_receipt_total_blocks_approval(decision_scenario):
    s = decision_scenario
    client, receipts = _receipt_collection()
    try:
        receipts.update_one(
            {"expense_id": s["expense_id"]},
            {"$set": {"total": Decimal128("900.00")}},
        )
    finally:
        client.close()

    with pytest.raises(MissingReceiptEvidence, match="does not match"):
        approve_expense(
            expense_id=s["expense_id"],
            approver_id=s["approver_id"],
            expected_version=s["version"],
        )

    _assert_unchanged(s)


def test_approval_persists_receipt_reference(decision_scenario):
    s = decision_scenario
    result = approve_expense(
        expense_id=s["expense_id"],
        approver_id=s["approver_id"],
        expected_version=s["version"],
    )
    assert result["status"] == "approved"

    with get_connection() as conn:
        rule_version, snapshot = conn.execute(
            """
            SELECT rule_version, evidence_snapshot
            FROM decisions
            WHERE expense_id = %s
              AND decision = 'approved'
            """,
            (s["expense_id"],),
        ).fetchone()

    assert rule_version == "expense-workflow-v2"
    assert snapshot["receipt"]["source"] == "mongodb"
    assert snapshot["receipt"]["expense_id"] == s["expense_id"]
    assert Decimal(snapshot["receipt"]["total"]) == Decimal("700")
    assert snapshot["receipt"]["check"] == "matched_expense_amount"
    assert snapshot["receipt"]["source_id"].startswith("mongodb:receipts:")


def test_rejection_remains_possible_without_receipt(decision_scenario):
    s = decision_scenario
    client, receipts = _receipt_collection()
    try:
        receipts.delete_many({"expense_id": s["expense_id"]})
    finally:
        client.close()

    result = reject_expense(
        expense_id=s["expense_id"],
        approver_id=s["approver_id"],
        expected_version=s["version"],
        reason="Receipt not provided",
    )
    assert result["status"] == "rejected"

    with get_connection() as conn:
        snapshot = conn.execute(
            "SELECT evidence_snapshot FROM decisions WHERE expense_id = %s",
            (s["expense_id"],),
        ).fetchone()[0]
    assert snapshot["receipt"] is None


def test_mongodb_outage_blocks_approval(decision_scenario, monkeypatch):
    s = decision_scenario

    def unavailable(**kwargs):
        raise ReceiptEvidenceUnavailable(
            "Receipt evidence is unavailable; approval cannot proceed"
        )

    monkeypatch.setattr(workflow, "require_receipt_evidence", unavailable)

    with pytest.raises(ReceiptEvidenceUnavailable):
        approve_expense(
            expense_id=s["expense_id"],
            approver_id=s["approver_id"],
            expected_version=s["version"],
        )

    _assert_unchanged(s)
