"""Read authoritative MongoDB receipt evidence before approving an expense."""

from decimal import Decimal, InvalidOperation

from bson.decimal128 import Decimal128
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.config import get_settings
from app.services.exceptions import (
    MissingReceiptEvidence,
    ReceiptEvidenceUnavailable,
)


def require_receipt_evidence(expense_id: int, expense_amount: Decimal) -> dict:
    """Return a decision-time observation of one matching receipt.

    Refuse approval if the receipt is absent, malformed, or its total does
    not match the expense. MongoDB remains the source of the document.
    """
    client = MongoClient(
        get_settings().mongo_uri,
        serverSelectionTimeoutMS=5000,
    )
    try:
        # The receipt schema requires these fields at write time. Recheck
        # them here because legacy or externally imported data may differ.
        receipt = client["expense_approval"]["receipts"].find_one(
            {"expense_id": expense_id},
            {
                "_id": 1,
                "vendor": 1,
                "country": 1,
                "vat_number": 1,
                "total": 1,
                "currency": 1,
                "receipt_date": 1,
            },
        )
    except PyMongoError as exc:
        # A database outage must not silently turn into "no receipt".
        raise ReceiptEvidenceUnavailable(
            "Receipt evidence is unavailable; approval cannot proceed"
        ) from exc
    finally:
        client.close()

    if receipt is None:
        raise MissingReceiptEvidence(
            "No receipt found for this expense"
        )

    required_text = ("vendor", "country", "vat_number", "currency")
    if any(
        not isinstance(receipt.get(key), str)
        or not receipt[key].strip()
        for key in required_text
    ):
        raise MissingReceiptEvidence("Receipt has incomplete required fields")

    receipt_date = receipt.get("receipt_date")
    if receipt_date is None or not hasattr(receipt_date, "isoformat"):
        raise MissingReceiptEvidence("Receipt has no valid receipt date")

    raw_total = receipt.get("total")
    try:
        total = (
            raw_total.to_decimal()
            if isinstance(raw_total, Decimal128)
            else Decimal(str(raw_total))
        )
    except (InvalidOperation, ValueError, TypeError):
        raise MissingReceiptEvidence("Receipt total is not numeric") from None

    if not total.is_finite() or total <= 0:
        raise MissingReceiptEvidence("Receipt total must be positive")

    if total != expense_amount:
        raise MissingReceiptEvidence(
            "Receipt total does not match expense amount"
        )

    return {
        "source": "mongodb",
        "source_id": f"mongodb:receipts:{receipt['_id']}",
        "expense_id": expense_id,
        "vendor": receipt["vendor"],
        "total": str(total),
        "currency": receipt["currency"],
        "receipt_date": receipt_date.isoformat(),
        # No source-version field is available in the current receipt schema.
        "source_version": None,
        "check": "matched_expense_amount",
    }
