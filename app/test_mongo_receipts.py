
from datetime import datetime, timezone
from decimal import Decimal

from bson.decimal128 import Decimal128
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import WriteError

import os

load_dotenv()

client = MongoClient(
    os.getenv("MONGO_URI", "mongodb://localhost:27017")
)

db = client["expense_approval"]
receipts = db["receipts"]

# Receipt from a Hungarian vendor
hungarian_receipt = {
    "expense_id": 5,
    "vendor": "Budapest Office Supplies",
    "country": "HU",
    "vat_number": "HU12345678",
    "total": Decimal128(Decimal("125.50")),
    "currency": "HUF",
    "receipt_date": datetime.now(timezone.utc),
    "details": {
        "invoice_number": "HU-2026-001",
        "tax_rate": 27,
        "payment_method": "card",
    },
}

# Receipt from a German vendor, with different extra fields
german_receipt = {
    "expense_id": 6,
    "vendor": "Berlin Software GmbH",
    "country": "DE",
    "vat_number": "DE123456789",
    "total": Decimal128(Decimal("89.99")),
    "currency": "EUR",
    "receipt_date": datetime.now(timezone.utc),
    "details": {
        "invoice_number": "DE-2026-045",
        "service_period": "2026-10",
        "software_license": True,
    },
}

for receipt in [hungarian_receipt, german_receipt]:
    result = receipts.insert_one(receipt)
    print(f"Valid receipt inserted: {result.inserted_id}")

# Deliberately invalid: missing VAT number and total
invalid_receipt = {
    "expense_id": 7,
    "vendor": "Invalid Test Vendor",
    "country": "HU",
    "currency": "HUF",
    "receipt_date": datetime.now(timezone.utc),
    "details": {
        "invoice_number": "INVALID-001",
    },
}

try:
    receipts.insert_one(invalid_receipt)
    print("ERROR: Invalid receipt was accepted!")
except WriteError as error:
    print("Expected validation failure:")
    print(error.details)

print("\nReceipts stored:")
for receipt in receipts.find({}, {"vendor": 1, "country": 1, "total": 1}):
    print(receipt)

client.close()
