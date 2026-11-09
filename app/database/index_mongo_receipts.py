import os

from bson.decimal128 import Decimal128
from dotenv import load_dotenv
from pymongo import MongoClient

from app.database.vector_store import (
    generate_embeddings,
    store_documents,
)

load_dotenv()

EXPECTED_RECEIPTS = 250


def receipt_to_text(receipt):
    """
    Convert a MongoDB receipt into searchable text.

    Uses the same primary text format as the
    duplicate-detection evaluation dataset.
    """

    total = receipt["total"]

    if isinstance(total, Decimal128):
        total = str(total.to_decimal())
    else:
        total = str(total)

    invoice_number = receipt["details"]["invoice_number"]

    receipt_date = (
        receipt["receipt_date"].date().isoformat()
    )

    return (
        f"{receipt['vendor']} receipt dated {receipt_date}. "
        f"Invoice number {invoice_number}. "
        f"Total amount {total} {receipt['currency']}."
    )


def load_receipts():
    client = MongoClient(os.getenv("MONGO_URI"))

    try:
        collection = client["expense_approval"]["receipts"]

        receipts = list(
            collection.find({
                "_id": {
                    "$regex": r"^synthetic_receipt_\d{4}$"
                }
            }).sort("_id", 1)
        )

        if len(receipts) != EXPECTED_RECEIPTS:
            raise RuntimeError(
                f"Expected {EXPECTED_RECEIPTS} receipts, "
                f"found {len(receipts)}"
            )

        documents = []

        for receipt in receipts:
            receipt_id = str(receipt["_id"])

            documents.append({
                "id": f"mongo_{receipt_id}",
                "document_type": "receipt",
                "text": receipt_to_text(receipt),
                "source_id": f"mongodb:receipts:{receipt_id}",
                "filter_group": "common",
            })

        return documents

    finally:
        client.close()


def main():
    documents = load_receipts()

    print("MongoDB receipts loaded:", len(documents))

    embeddings = generate_embeddings(documents)

    # Upsert these 250 documents without deleting the
    # existing vector dataset.
    store_documents(documents, embeddings)

    print("\nSUCCESS: MongoDB receipts indexed.")
    print("New receipt document IDs use the prefix 'mongo_'.")

    print(
        "Expected total vector documents: "
        "205 original + 250 MongoDB receipts = 455"
    )


if __name__ == "__main__":
    main()