"""Show source -> stale derived copies -> refreshed copies using isolated test databases.

Run with:
    python scripts/run_integration_tests.py -s -v tests/integration/test_source_refresh.py

All records created here are test-only and removed during fixture cleanup.
"""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4, uuid5, NAMESPACE_URL

import numpy as np
import pytest
from bson.decimal128 import Decimal128
from pymongo import MongoClient
from qdrant_client import models

from app.config import get_settings
from app.database.mongo_setup import setup_receipts_collection
from app.database.postgres import get_connection
from app.database.qdrant import get_qdrant_client
from app.database.vector_store import (
    COLLECTION_NAME,
    setup_postgres,
    setup_qdrant,
    store_documents,
)

pytestmark = pytest.mark.integration


def _document(receipt, document_id):
    """Derive searchable content from the current authoritative receipt."""
    amount = receipt["total"].to_decimal()
    return {
        "id": document_id,
        "document_type": "receipt",
        "source_id": f"mongodb:receipts:{receipt['_id']}",
        "source_version": receipt["source_version"],
        "filter_group": "test",
        "text": (
            f"{receipt['vendor']} receipt for "
            f"{amount} {receipt['currency']}"
        ),
    }


def _derived(document_id):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT source_id, source_version, content, refreshed_at
            FROM vector_documents WHERE id = %s
            """,
            (document_id,),
        ).fetchone()

    point_id = str(uuid5(NAMESPACE_URL, document_id))
    points = get_qdrant_client().retrieve(
        collection_name=COLLECTION_NAME,
        ids=[point_id],
        with_payload=True,
    )
    assert row is not None
    assert len(points) == 1
    return {
        "postgres": {
            "source_id": row[0],
            "source_version": row[1],
            "content": row[2],
            "refreshed_at": row[3].isoformat(),
        },
        "qdrant": points[0].payload,
    }


@pytest.mark.integration
def test_source_change_stale_then_refresh():
    setup_receipts_collection()
    setup_postgres()
    setup_qdrant()

    # Each run gets independent, disposable records in the test databases.
    run_id = uuid4().hex
    receipt_id = f"pytest-source-refresh-{run_id}"
    document_id = f"pytest-vector-refresh-{run_id}"
    point_id = str(uuid5(NAMESPACE_URL, document_id))
    mongo = MongoClient(get_settings().mongo_uri)
    receipts = mongo["expense_approval"]["receipts"]

    try:
        receipts.insert_one({
            "_id": receipt_id,
            "expense_id": 900000001,
            "vendor": "Original Vendor",
            "country": "HU",
            "vat_number": "HU12345678",
            "total": Decimal128(Decimal("125.50")),
            "currency": "EUR",
            "receipt_date": datetime(2026, 11, 26, tzinfo=timezone.utc),
            "source_version": 1,
        })
        source_v1 = receipts.find_one({"_id": receipt_id})
        document_v1 = _document(source_v1, document_id)

        # Deterministic 384-D test vectors isolate data propagation from
        # model quality/downloads. This is not a vector-quality benchmark.
        embedding_v1 = np.zeros(384, dtype=np.float32)
        embedding_v1[0] = 1.0
        store_documents([document_v1], [embedding_v1])
        derived_v1 = _derived(document_id)
        assert derived_v1["postgres"]["source_version"] == 1
        assert derived_v1["qdrant"]["source_version"] == 1

        # Update the authoritative source ONLY: derived copies remain stale.
        updated = receipts.update_one(
            {"_id": receipt_id, "source_version": 1},
            {
                "$set": {
                    "vendor": "Corrected Vendor",
                    "total": Decimal128(Decimal("140.00")),
                },
                "$inc": {"source_version": 1},
            },
        )
        assert updated.modified_count == 1
        source_v2 = receipts.find_one({"_id": receipt_id})
        stale = _derived(document_id)

        assert source_v2["source_version"] == 2
        for store in ("postgres", "qdrant"):
            assert stale[store]["source_version"] == 1
            assert stale[store]["content"] == document_v1["text"]

        print("\nBEFORE: source v1, pgvector v1, Qdrant v1")
        print("  source ID:", document_v1["source_id"])
        print("  old content:", document_v1["text"])
        print("  pgvector refreshed_at:", derived_v1["postgres"]["refreshed_at"])
        print("  Qdrant refreshed_at:", derived_v1["qdrant"]["refreshed_at"])
        print("STALE: source v2, pgvector v1, Qdrant v1")
        print("  source content:", _document(source_v2, document_id)["text"])
        print("  derived content:", stale["postgres"]["content"])

        # Re-read source and upsert the same document ID to both indexes.
        document_v2 = _document(source_v2, document_id)
        embedding_v2 = np.zeros(384, dtype=np.float32)
        embedding_v2[1] = 1.0
        store_documents([document_v2], [embedding_v2])
        refreshed = _derived(document_id)

        for store in ("postgres", "qdrant"):
            assert refreshed[store]["source_id"] == document_v2["source_id"]
            assert refreshed[store]["source_version"] == 2
            assert refreshed[store]["content"] == document_v2["text"]
            assert refreshed[store]["refreshed_at"] >= stale[store]["refreshed_at"]

        with get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM vector_documents WHERE id = %s",
                (document_id,),
            ).fetchone()[0] == 1

        print("REFRESHED: source v2, pgvector v2, Qdrant v2")
        print("  new content:", document_v2["text"])
        print("  pgvector refreshed_at:", refreshed["postgres"]["refreshed_at"])
        print("  Qdrant refreshed_at:", refreshed["qdrant"]["refreshed_at"])
        print("  status: copies match the source version")

    finally:
        try:
            receipts.delete_one({"_id": receipt_id})
            with get_connection() as conn:
                conn.execute(
                    "DELETE FROM vector_documents WHERE id = %s",
                    (document_id,),
                )
        finally:
            client = get_qdrant_client()
            try:
                if client.collection_exists(COLLECTION_NAME):
                    client.delete(
                        collection_name=COLLECTION_NAME,
                        points_selector=models.PointIdsList(points=[point_id]),
                        wait=True,
                    )
            finally:
                mongo.close()
