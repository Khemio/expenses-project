"""Print reproducible labelled decision outcomes (pure evaluator only).

Run from repository root:
    python -m scripts.report_labeled_decisions
This is distinct from the database-backed approval workflow.
"""
import json
from collections import Counter
from pathlib import Path

from app.services.decision_service import evaluate_expense


ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "expense_test_cases.json"


def main() -> None:
    cases = json.loads(LABELS.read_text(encoding="utf-8"))
    if len(cases) != 25 or len({c["id"] for c in cases}) != 25:
        raise ValueError("Expected 25 unique pre-labelled expense cases")

    expected_counts = Counter()
    mismatches = []
    for case in cases:
        actual = evaluate_expense(
            amount=case["amount"],
            budget_remaining=case["budget_remaining"],
            budget_version_matches=case["budget_version_matches"],
            valid_approver=case["valid_approver"],
            requires_escalation=case["requires_escalation"],
        )
        expected_counts[case["expected"]] += 1
        if actual != case["expected"]:
            mismatches.append(
                {"id": case["id"], "expected": case["expected"], "actual": actual}
            )

    correct = len(cases) - len(mismatches)
    print("LABELLED DECISION EVALUATION — pure evaluator, not production workflow")
    print("  cases:", len(cases))
    print("  expected approved:", expected_counts["approved"])
    print("  expected rejected:", expected_counts["rejected"])
    print("  expected escalated:", expected_counts["escalated"])
    print("  correct:", correct)
    print("  accuracy:", f"{correct}/{len(cases)} = {correct / len(cases):.4f}")
    print("  mismatches:", json.dumps(mismatches, indent=2))
    print("  limitations: does not query MongoDB, Neo4j or PostgreSQL")

    if mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
