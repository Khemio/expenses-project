
import json
import random
from pathlib import Path

random.seed(42)

OUTPUT_FILE = Path("data/vector_documents.json")

VENDORS = [
    "Office Supplies Ltd",
    "City Taxi",
    "Tech Store",
    "Hotel Central",
    "Air Travel Services",
    "Business Meals GmbH",
    "Print Solutions",
    "Furniture World",
    "Software Cloud",
    "Rail Travel Ltd",
]

CATEGORIES = [
    "office supplies",
    "taxi travel",
    "computer equipment",
    "hotel accommodation",
    "air travel",
    "business meals",
    "printing",
    "office furniture",
    "software subscriptions",
    "rail travel",
]

POLICIES = [
    "Business travel is reimbursable when it is necessary for approved company activities.",
    "Taxi expenses are reimbursable when public transport is unavailable or impractical.",
    "Hotel accommodation must be reasonable and must not exceed the approved nightly allowance.",
    "Computer equipment purchases require manager approval before the purchase is made.",
    "Business meals must have a clear business purpose and include the names of attendees.",
    "Office supplies may be purchased within the approved cost centre budget.",
    "Air travel should use economy class unless an exception is approved by management.",
    "Receipts must include the vendor name, VAT number, transaction date and total amount.",
    "Software subscriptions must be approved by the responsible department manager.",
    "Rail travel is preferred over air travel for eligible short-distance business journeys.",
    "Expenses above the employee's approval limit must be escalated to a higher approver.",
    "Accommodation upgrades and personal expenses are not reimbursable.",
    "Employees must submit expenses within 30 days of the transaction date.",
    "Duplicate expense claims must be rejected and investigated.",
    "Purchases must be assigned to the correct company cost centre.",
    "Expenses must not exceed the remaining approved budget.",
    "A manager may approve expenses only within their delegated authority.",
    "Foreign currency expenses must include the original amount and currency.",
    "VAT information must be present where required by local tax rules.",
    "Expenses with missing supporting documentation may be rejected.",
]

def generate_receipts():
    documents = []

    for i in range(1, 101):
        vendor_index = (i - 1) % len(VENDORS)
        vendor = VENDORS[vendor_index]
        category = CATEGORIES[vendor_index]

        amount = round(random.uniform(15, 900), 2)
        invoice_number = f"INV-{i:04d}"

        text = (
            f"{vendor} invoice {invoice_number}. "
            f"Purchase of {category}. "
            f"Total amount {amount:.2f} EUR."
        )

        documents.append({
            "id": f"receipt_{i:03d}",
            "document_type": "receipt",
            "text": text,
            "source_id": f"receipt_{i:03d}",
            "filter_group": "rare" if i <= 10 else "common",
        })

    # Add 5 deliberately similar receipts to test duplicate detection.
    original = documents[0]["text"]

    for i in range(101, 106):
        documents.append({
            "id": f"receipt_{i:03d}",
            "document_type": "receipt",
            "text": original.replace(
                "Purchase of office supplies",
                "Purchase of office stationery"
            ),
            "source_id": f"receipt_{i:03d}",
            "filter_group": "common",
        })

    return documents


def generate_policies():
    documents = []

    for i in range(1, 101):
        policy = POLICIES[(i - 1) % len(POLICIES)]

        documents.append({
            "id": f"policy_{i:03d}",
            "document_type": "policy",
            "text": f"Expense Policy Section {i}. {policy}",
            "source_id": f"policy_{i:03d}",
            "filter_group": "common",
        })

    return documents


def main():
    documents = generate_receipts() + generate_policies()

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(documents, file, indent=2, ensure_ascii=False)

    print("Dataset generated successfully.")
    print("Total documents:", len(documents))
    print(
        "Receipts:",
        sum(d["document_type"] == "receipt" for d in documents)
    )
    print(
        "Policies:",
        sum(d["document_type"] == "policy" for d in documents)
    )
    print(
        "Rare filter records:",
        sum(d["filter_group"] == "rare" for d in documents)
    )
    print("Output:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
