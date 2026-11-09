import json
import os
from pathlib import Path

from bson.decimal128 import Decimal128
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

OUTPUT = Path("data/duplicate_test_cases.json")


def format_total(receipt):
    total = receipt["total"]

    if isinstance(total, Decimal128):
        return str(total.to_decimal())

    return str(total)


def receipt_text(receipt, alternative=False):
    vendor = receipt["vendor"]
    invoice = receipt["details"]["invoice_number"]
    total = format_total(receipt)
    currency = receipt["currency"]
    date = receipt["receipt_date"].date().isoformat()

    if alternative:
        return (
            f"Invoice {invoice} issued by {vendor}. "
            f"Date: {date}. Amount payable: {total} {currency}."
        )

    return (
        f"{vendor} receipt dated {date}. "
        f"Invoice number {invoice}. "
        f"Total amount {total} {currency}."
    )


def main():
    if OUTPUT.exists():
        raise FileExistsError(
            f"{OUTPUT} already exists. "
            "Preserving existing evaluation labels."
        )

    client = MongoClient(os.getenv("MONGO_URI"))

    try:
        collection = client["expense_approval"]["receipts"]

        receipts = list(
            collection.find(
                {
                    "_id": {
                        "$regex": r"^synthetic_receipt_\d{4}$"
                    }
                }
            ).sort("_id", 1)
        )

    finally:
        client.close()

    assert len(receipts) == 250

    cases = []

    # 10 positive pairs:
    # Two textual representations of the same receipt.
    for i in range(10):
        receipt = receipts[i]

        cases.append({
            "id": f"DUP{i + 1:02d}",
            "receipt_a": str(receipt["_id"]),
            "receipt_b": str(receipt["_id"]),
            "text_a": receipt_text(receipt),
            "text_b": receipt_text(receipt, alternative=True),
            "expected_duplicate": True,
        })

    # 15 negative pairs:
    # Receipts belonging to different expenses.
    for i in range(15):
        receipt_a = receipts[10 + i]
        receipt_b = receipts[25 + i]

        assert (
            receipt_a["expense_id"] != receipt_b["expense_id"]
        )

        cases.append({
            "id": f"DUP{i + 11:02d}",
            "receipt_a": str(receipt_a["_id"]),
            "receipt_b": str(receipt_b["_id"]),
            "text_a": receipt_text(receipt_a),
            "text_b": receipt_text(receipt_b, alternative=True),
            "expected_duplicate": False,
        })

    assert len(cases) == 25
    assert sum(
        case["expected_duplicate"] for case in cases
    ) == 10

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT.open("w", encoding="utf-8") as file:
        json.dump(cases, file, indent=2, ensure_ascii=False)

    print("SUCCESS: Duplicate test cases generated.")
    print("Total pairs:", len(cases))
    print("Positive pairs:", 10)
    print("Negative pairs:", 15)
    print("Output:", OUTPUT)


if __name__ == "__main__":
    main()