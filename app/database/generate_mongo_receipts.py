import os
import random
import re
from datetime import datetime, time, timezone
from decimal import Decimal

import psycopg
from bson.decimal128 import Decimal128
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne

load_dotenv()

SEED = 42
EXPECTED_RECEIPTS = 250

EXPENSE_MARKER = re.compile(r"^\[SYNTH-EXP-(\d{4})\]")

VENDORS = {
    "HU": [
        "Danube Business Supplies",
        "Budapest Technology Services",
        "Pannon Office Solutions",
    ],
    "DE": [
        "Berlin Business Equipment",
        "Munich Software Services",
        "Rhein Professional Supplies",
    ],
    "AT": [
        "Vienna Office Systems",
        "Alpine Business Services",
    ],
    "NL": [
        "Amsterdam Technology Group",
        "Dutch Business Solutions",
    ],
}

COUNTRIES = list(VENDORS.keys())


def load_postgres_expenses():
    """
    Retrieve synthetic expenses from PostgreSQL.

    PostgreSQL remains the source of record for
    expense IDs, amounts, descriptions and dates.
    """

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    amount,
                    description,
                    expense_date
                FROM expenses
                WHERE description LIKE '[SYNTH-EXP-%'
                ORDER BY id
                """
            )

            rows = cur.fetchall()

    expenses = {}

    for expense_id, amount, description, expense_date in rows:
        match = EXPENSE_MARKER.match(description)

        if match is None:
            continue

        number = int(match.group(1))

        if number in expenses:
            raise RuntimeError(
                f"Duplicate synthetic expense number: {number}"
            )

        expenses[number] = {
            "expense_id": expense_id,
            "amount": amount,
            "description": description,
            "expense_date": expense_date,
        }

    expected_numbers = set(range(1, EXPECTED_RECEIPTS + 1))

    if set(expenses) != expected_numbers:
        raise RuntimeError(
            "Expected exactly 250 numbered synthetic expenses. "
            "Verify PostgreSQL data before generating receipts."
        )

    return expenses


def generate_vat_number(country, rng):
    """
    Generate synthetic VAT-like identifiers.

    These are demonstration identifiers, not
    verified or legally valid VAT registrations.
    """

    if country == "HU":
        return f"HU{rng.randint(10000000, 99999999)}"

    if country == "DE":
        return f"DE{rng.randint(100000000, 999999999)}"

    if country == "AT":
        return f"ATU{rng.randint(10000000, 99999999)}"

    if country == "NL":
        return f"NL{rng.randint(100000000, 999999999)}B01"

    raise ValueError(f"Unsupported country: {country}")


def generate_details(description, number, country, rng):
    """
    Generate flexible receipt details based on
    the expense category.
    """

    details = {
        "invoice_number": f"{country}-SYN-{number:05d}",
        "payment_method": rng.choice(
            ["company_card", "bank_transfer", "employee_card"]
        ),
        "synthetic": True,
    }

    text = description.lower()

    if "software subscription" in text:
        details.update({
            "software_license": True,
            "billing_period": "monthly",
            "license_count": rng.randint(1, 25),
        })

    elif "business travel" in text:
        details.update({
            "travel_category": rng.choice(
                ["rail", "hotel", "airfare"]
            ),
            "business_purpose": "Client or internal meeting",
        })

    elif "professional training" in text:
        details.update({
            "training_type": rng.choice(
                ["technical", "management", "compliance"]
            ),
            "attendee_count": rng.randint(1, 8),
        })

    elif "office equipment" in text:
        details.update({
            "equipment_category": rng.choice(
                ["monitor", "keyboard", "printer", "desk"]
            ),
            "warranty_months": 24,
        })

    elif "conference registration" in text:
        details.update({
            "registration_type": "professional",
            "attendee_count": rng.randint(1, 5),
        })

    else:
        details.update({
            "purchase_category": "general_business",
            "item_count": rng.randint(1, 15),
        })

    if country == "HU":
        details["tax_rate"] = 27

    elif country == "DE":
        details["tax_rate"] = 19

    elif country == "AT":
        details["tax_rate"] = 20

    elif country == "NL":
        details["tax_rate"] = 21

    return details


def build_receipt(number, expense, rng):
    country = rng.choice(COUNTRIES)
    vendor = rng.choice(VENDORS[country])

    # PostgreSQL NUMERIC converts naturally to Decimal.
    amount = Decimal(str(expense["amount"]))

    receipt_date = datetime.combine(
        expense["expense_date"],
        time(hour=12),
        tzinfo=timezone.utc,
    )

    receipt_id = f"synthetic_receipt_{number:04d}"

    return {
        "_id": receipt_id,

        # Reference to the PostgreSQL expense.
        "expense_id": int(expense["expense_id"]),

        "vendor": vendor,
        "country": country,
        "vat_number": generate_vat_number(country, rng),

        # Decimal128 preserves monetary decimal precision.
        "total": Decimal128(str(amount)),
        "currency": "EUR",

        "receipt_date": receipt_date,

        "details": generate_details(
            expense["description"],
            number,
            country,
            rng,
        ),
    }


def main():
    rng = random.Random(SEED)

    expenses = load_postgres_expenses()

    print("PostgreSQL synthetic expenses:", len(expenses))

    client = MongoClient(os.getenv("MONGO_URI"))

    try:
        db = client["expense_approval"]
        collection = db["receipts"]

        operations = []

        for number in sorted(expenses):
            receipt = build_receipt(
                number,
                expenses[number],
                rng,
            )

            # Insert only if this receipt does not already exist.
            # This protects the data when the generator is rerun.
            operations.append(
                UpdateOne(
                    {"_id": receipt["_id"]},
                    {"$setOnInsert": receipt},
                    upsert=True,
                )
            )

        result = collection.bulk_write(
            operations,
            ordered=True,
        )

        print("\nMongoDB generation completed.")
        print("New receipts inserted:", result.upserted_count)
        print("Existing receipts matched:", result.matched_count)

        # Independently verify the resulting collection.
        synthetic_count = collection.count_documents({
            "_id": {
                "$regex": r"^synthetic_receipt_\d{4}$"
            }
        })

        total_count = collection.count_documents({})

        print("\nVerification:")
        print("Synthetic receipts:", synthetic_count)
        print("Total MongoDB receipts:", total_count)

        assert synthetic_count == EXPECTED_RECEIPTS, (
            f"Expected {EXPECTED_RECEIPTS} synthetic receipts, "
            f"found {synthetic_count}"
        )

        # Verify all generated documents use valid expense IDs.
        expected_ids = {
            expense["expense_id"]
            for expense in expenses.values()
        }

        receipt_expense_ids = {
            receipt["expense_id"]
            for receipt in collection.find(
                {
                    "_id": {
                        "$regex": r"^synthetic_receipt_\d{4}$"
                    }
                },
                {"expense_id": 1},
            )
        }

        assert receipt_expense_ids == expected_ids, (
            "MongoDB expense references do not match PostgreSQL"
        )

        print("PostgreSQL references verified: True")
        print(
            "\nSUCCESS: MongoDB synthetic receipts "
            "generated and verified."
        )

    finally:
        client.close()


if __name__ == "__main__":
    main()