
import json
from collections import Counter
from pathlib import Path

from app.services.decision_service import evaluate_expense


DATA_FILE = Path("data/expense_test_cases.json")


def main():
    with DATA_FILE.open("r", encoding="utf-8") as file:
        cases = json.load(file)

    correct = 0
    predictions = Counter()

    for case in cases:
        predicted = evaluate_expense(
            amount=case["amount"],
            budget_remaining=case["budget_remaining"],
            budget_version_matches=case["budget_version_matches"],
            valid_approver=case["valid_approver"],
            requires_escalation=case["requires_escalation"],
        )

        expected = case["expected"]
        predictions[predicted] += 1

        passed = predicted == expected
        correct += passed

        print(
            f"{case['id']}: "
            f"expected={expected:<10} "
            f"predicted={predicted:<10} "
            f"{'PASS' if passed else 'FAIL'}"
        )

    accuracy = correct / len(cases)

    print("\n--- Evaluation summary ---")
    print("Total cases:", len(cases))
    print("Correct predictions:", correct)
    print(f"Accuracy: {accuracy:.2%}")

    print("\nPredicted outcomes:")
    for outcome in ("approved", "rejected", "escalated"):
        print(f"  {outcome}: {predictions[outcome]}")

    if correct != len(cases):
        raise AssertionError("Some expense cases failed")


if __name__ == "__main__":
    main()
