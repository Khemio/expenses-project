
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from bson.decimal128 import Decimal128
from pymongo import MongoClient
from pymongo.errors import WriteError

from app.config import get_settings
from app.database.mongo_setup import setup_receipts_collection


@pytest.fixture
def receipts_collection():
    # Configure schema validation using application code.
    setup_receipts_collection()

    client = MongoClient(get_settings().mongo_uri)

    try:
        collection = client["expense_approval"]["receipts"]
        created_ids = []

        yield collection, created_ids

    finally:
        if created_ids:
            collection.delete_many(
                {"_id": {"$in": created_ids}}
            )
        client.close()


def make_receipt():
    return {
        "expense_id": 1,
        "vendor": f"Test Vendor {uuid4().hex}",
        "country": "HU",
        "vat_number": "HU12345678",
        "total": Decimal128(Decimal("125.50")),
        "currency": "HUF",
        "receipt_date": datetime.now(timezone.utc),
        "details": {
            "payment_method": "card",
        },
    }


@pytest.mark.integration
def test_valid_receipt_is_stored(receipts_collection):
    collection, created_ids = receipts_collection

    receipt = make_receipt()
    result = collection.insert_one(receipt)
    created_ids.append(result.inserted_id)

    stored = collection.find_one(
        {"_id": result.inserted_id}
    )

    assert stored["vendor"] == receipt["vendor"]
    assert stored["total"] == Decimal128(
        Decimal("125.50")
    )
    assert stored["country"] == "HU"


@pytest.mark.integration
def test_receipt_missing_required_fields_is_rejected(
    receipts_collection,
):
    collection, _ = receipts_collection

    invalid_receipt = make_receipt()
    del invalid_receipt["total"]
    del invalid_receipt["vat_number"]

    with pytest.raises(WriteError):
        collection.insert_one(invalid_receipt)

    assert collection.count_documents({
        "vendor": invalid_receipt["vendor"]
    }) == 0


@pytest.mark.integration
def test_schema_setup_preserves_existing_receipts(
    receipts_collection,
):
    collection, created_ids = receipts_collection

    receipt = make_receipt()
    result = collection.insert_one(receipt)
    created_ids.append(result.inserted_id)

    # Applying schema validation again must not
    # drop the existing collection or its data.
    setup_receipts_collection()

    assert collection.find_one({
        "_id": result.inserted_id
    }) is not None
