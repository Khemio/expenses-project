import json
from pathlib import Path

DATA_FILE = Path("data/duplicate_test_cases.json")

FALSE_POSITIVE_IDS = {"DUP16", "DUP18", "DUP21"}


def main():
    with DATA_FILE.open("r", encoding="utf-8") as file:
        cases = json.load(file)

    for case in cases:
        if case["id"] not in FALSE_POSITIVE_IDS:
            continue

        print("=" * 70)
        print("Test case:", case["id"])
        print("Receipt A:", case["receipt_a"])
        print("Receipt B:", case["receipt_b"])
        print("Expected duplicate:", case["expected_duplicate"])

        print("\nTEXT A:")
        print(case["text_a"])

        print("\nTEXT B:")
        print(case["text_b"])
        print()

if __name__ == "__main__":
    main()