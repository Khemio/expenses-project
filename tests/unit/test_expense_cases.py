
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


@pytest.mark.parametrize(
    "case",
    json.loads(DATA_FILE.read_text(encoding="utf-8")),
    ids=lambda case: case["id"],
)
def test_evaluate_expense_against_labeled_case(case):
    actual = evaluate_expense(
        amount=case["amount"],
        budget_remaining=case["budget_remaining"],
        budget_version_matches=case[
            "budget_version_matches"
        ],
        valid_approver=case["valid_approver"],
        requires_escalation=case[
            "requires_escalation"
        ],
    )

    assert actual == case["expected"]



@pytest.mark.parametrize(
    "amount,remaining,expected",
    [
        (0, 100, "rejected"),
        (-10, 100, "rejected"),
        ("0.01", "0.01", "approved"),
        ("99.99", "100.00", "approved"),
        ("100.01", "100.00", "rejected"),
        ("100.00", "100.00", "approved"),
    ],
)
def test_expense_amount_boundaries(
    amount,
    remaining,
    expected,
):
    result = evaluate_expense(
        amount=amount,
        budget_remaining=remaining,
        budget_version_matches=True,
        valid_approver=True,
        requires_escalation=False,
    )

    assert result == expected
