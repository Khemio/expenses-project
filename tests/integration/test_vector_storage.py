
import uuid

import numpy as np
import pytest
from qdrant_client import models

from app.database.postgres import get_connection
from app.database.qdrant import get_qdrant_client
from app.database.vector_store import (
    COLLECTION_NAME,
    setup_postgres,
    setup_qdrant,
    store_documents,
)


@pytest.fixture
def vector_document():
    setup_postgres()
    setup_qdrant()

    document_id = f"pytest-vector-{uuid.uuid4().hex}"
    point_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, document_id)
    )

    document = {
        "id": document_id,
        "document_type": "policy",
        "text": "Employees may purchase office equipment.",
        "source_id": "integration-test",
        "filter_group": "test",
    }

    vector = np.zeros(384, dtype=np.float32)
    vector[0] = 1.0

    try:
        yield document, vector, point_id
    finally:
        # Both cleanup operations are independently attempted,
        # including when a write only partially succeeds.
        try:
            with get_connection() as conn:
                conn.execute(
                    "DELETE FROM vector_documents WHERE id = %s",
                    (document_id,),
                )
        finally:
            client = get_qdrant_client()

            if client.collection_exists(COLLECTION_NAME):
                client.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=models.PointIdsList(
                        points=[point_id]
                    ),
                    wait=True,
                )


@pytest.mark.integration
def test_document_stored_in_both_vector_databases(
    vector_document,
):
    document, vector, point_id = vector_document

    store_documents(
        documents=[document],
        embeddings=[vector],
    )

    # PostgreSQL verification
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, document_type, content, filter_group
            FROM vector_documents
            WHERE id = %s
            """,
            (document["id"],),
        ).fetchone()

    assert row == (
        document["id"],
        "policy",
        document["text"],
        "test",
    )

    # Qdrant verification
    points = get_qdrant_client().retrieve(
        collection_name=COLLECTION_NAME,
        ids=[point_id],
        with_payload=True,
        with_vectors=True,
    )

    assert len(points) == 1

    point = points[0]
    assert point.payload["document_id"] == document["id"]
    assert point.payload["document_type"] == "policy"
    assert point.payload["content"] == document["text"]
    assert point.payload["filter_group"] == "test"

    # Check vector dimensions and approximate values.
    assert len(point.vector) == 384
    assert point.vector[0] == pytest.approx(1.0)



@pytest.mark.integration
def test_repeated_storage_updates_existing_document(
    vector_document,
):
    document, vector, point_id = vector_document

    # First write.
    store_documents([document], [vector])

    # Update the document and its embedding.
    updated_document = {
        **document,
        "text": "Updated policy: equipment needs approval.",
        "filter_group": "updated",
    }

    updated_vector = np.zeros(384, dtype=np.float32)
    updated_vector[1] = 1.0

    store_documents(
        [updated_document],
        [updated_vector],
    )

    # PostgreSQL must contain one updated row.
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT content, filter_group
            FROM vector_documents
            WHERE id = %s
            """,
            (document["id"],),
        ).fetchall()

    assert rows == [
        (
            updated_document["text"],
            "updated",
        )
    ]

    # Qdrant must contain one updated point.
    points = get_qdrant_client().retrieve(
        collection_name=COLLECTION_NAME,
        ids=[point_id],
        with_payload=True,
        with_vectors=True,
    )

    assert len(points) == 1

    point = points[0]

    assert point.payload["content"] == updated_document["text"]
    assert point.payload["filter_group"] == "updated"

    assert len(point.vector) == 384
    assert point.vector[0] == pytest.approx(0.0)
    assert point.vector[1] == pytest.approx(1.0)
