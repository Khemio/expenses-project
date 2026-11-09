
import json
from collections import Counter
from pathlib import Path

DATA_FILE = Path("data/expense_test_cases.json")

def main():
    with DATA_FILE.open("r", encoding="utf-8") as file:
        cases = json.load(file)

    assert len(cases) == 25, "Expected exactly 25 cases"

    ids = [case["id"] for case in cases]
    assert len(set(ids)) == 25, "Duplicate test case IDs"

    allowed_outcomes = {"approved", "rejected", "escalated"}

    for case in cases:
        assert case["expected"] in allowed_outcomes
        assert case["amount"] > 0
        assert case["budget_remaining"] >= 0
        assert isinstance(case["budget_version_matches"], bool)
        assert isinstance(case["valid_approver"], bool)
        assert isinstance(case["requires_escalation"], bool)

    counts = Counter(case["expected"] for case in cases)

    print("Total labelled expense cases:", len(cases))
    print("Expected outcome distribution:")
    for outcome in sorted(allowed_outcomes):
        print(f"  {outcome}: {counts[outcome]}")

    print("\nSUCCESS: All 25 test cases are structurally valid.")

if __name__ == "__main__":
    main()
