
import json
from pathlib import Path

import pytest

from app.services.decision_service import evaluate_expense


DATA_FILE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "expense_test_cases.json"
)


@pytest.fixture(scope="module")
def expense_cases():
    return json.loads(
        DATA_FILE.read_text(encoding="utf-8")
    )


def test_expense_case_dataset_is_valid(expense_cases):
    assert len(expense_cases) == 25

    ids = [case["id"] for case in expense_cases]
    assert len(ids) == len(set(ids))

    allowed_outcomes = {
        "approved",
        "rejected",
        "escalated",
    }

    for case in expense_cases:
        assert case["expected"] in allowed_outcomes
        assert case["amount"] > 0
        assert case["budget_remaining"] >= 0
        assert isinstance(
            case["budget_version_matches"], bool
        )
        assert isinstance(case["valid_approver"], bool)
        assert isinstance(
            case["requires_escalation"], bool
        )
