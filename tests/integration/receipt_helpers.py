"""Test-only MongoDB receipt fixtures tied to isolated PostgreSQL expenses."""

from datetime import datetime, timezone
from decimal import Decimal

from bson.decimal128 import Decimal128
from pymongo import MongoClient

from app.config import get_settings


TEST_VENDOR = "Integration Test Vendor"


def add_test_receipt(expense_id: int, amount=700) -> None:
    with MongoClient(get_settings().mongo_uri) as client:
        client["expense_approval"]["receipts"].insert_one(
            {
                "expense_id": expense_id,
                "vendor": TEST_VENDOR,
                "country": "HU",
                "vat_number": "HU12345678",
                "total": Decimal128(Decimal(str(amount))),
                "currency": "EUR",
                "receipt_date": datetime(2026, 11, 9, tzinfo=timezone.utc),
            }
        )


def delete_test_receipts(expense_ids: list[int]) -> None:
    if not expense_ids:
        return

    with MongoClient(get_settings().mongo_uri) as client:
        client["expense_approval"]["receipts"].delete_many(
            {
                "expense_id": {"$in": expense_ids},
                "vendor": TEST_VENDOR,
            }
        )
