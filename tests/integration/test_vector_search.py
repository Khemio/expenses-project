
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


def point_id_for(document_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, document_id))


@pytest.fixture
def search_dataset():
    setup_postgres()
    setup_qdrant()

    run_id = uuid.uuid4().hex

    documents = [
        {
            "id": f"pytest-{run_id}-travel-policy",
            "document_type": "policy",
            "text": "Business travel expenses are reimbursable.",
            "source_id": "integration-test",
            "filter_group": "travel",
        },
        {
            "id": f"pytest-{run_id}-equipment-policy",
            "document_type": "policy",
            "text": "Equipment purchases require approval.",
            "source_id": "integration-test",
            "filter_group": "equipment",
        },
        {
            "id": f"pytest-{run_id}-taxi-receipt",
            "document_type": "receipt",
            "text": "Taxi fare for a business meeting.",
            "source_id": "integration-test",
            "filter_group": "travel",
        },
    ]

    embeddings = np.zeros((3, 384), dtype=np.float32)

    for index in range(3):
        embeddings[index, index] = 1.0

    document_ids = [doc["id"] for doc in documents]
    point_ids = [point_id_for(doc_id) for doc_id in document_ids]

    try:
        store_documents(documents, embeddings)
        yield documents, embeddings

    finally:
        # Clean up both databases independently.
        try:
            with get_connection() as conn:
                conn.execute(
                    """
                    DELETE FROM vector_documents
                    WHERE id = ANY(%s)
                    """,
                    (document_ids,),
                )
        finally:
            client = get_qdrant_client()

            if client.collection_exists(COLLECTION_NAME):
                client.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=models.PointIdsList(
                        points=point_ids
                    ),
                    wait=True,
                )


@pytest.mark.integration
def test_similarity_search_agrees_on_nearest_document(
    search_dataset,
):
    documents, embeddings = search_dataset

    query_vector = embeddings[0].tolist()
    expected_id = documents[0]["id"]

    # PostgreSQL cosine-distance search.
    with get_connection() as conn:
        pg_results = conn.execute(
            """
            SELECT id
            FROM vector_documents
            WHERE source_id = %s
            ORDER BY embedding <=> %s::vector
            LIMIT 3
            """,
            ("integration-test", query_vector),
        ).fetchall()

    # Qdrant cosine-similarity search.
    qdrant_results = get_qdrant_client().query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=3,
        with_payload=True,
    ).points

    assert pg_results[0][0] == expected_id

    assert (
        qdrant_results[0].payload["document_id"]
        == expected_id
    )


@pytest.mark.integration
def test_metadata_filtering_agrees_between_stores(
    search_dataset,
):
    documents, embeddings = search_dataset

    query_vector = embeddings[0].tolist()

    expected_id = documents[2]["id"]

    # Filter using PostgreSQL columns.
    with get_connection() as conn:
        pg_results = conn.execute(
            """
            SELECT id
            FROM vector_documents
            WHERE document_type = %s
              AND filter_group = %s
              AND source_id = %s
            ORDER BY embedding <=> %s::vector
            LIMIT 5
            """,
            (
                "receipt",
                "travel",
                "integration-test",
                query_vector,
            ),
        ).fetchall()

    # Equivalent Qdrant payload filter.
    qdrant_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="document_type",
                match=models.MatchValue(value="receipt"),
            ),
            models.FieldCondition(
                key="filter_group",
                match=models.MatchValue(value="travel"),
            ),
            models.FieldCondition(
                key="source_id",
                match=models.MatchValue(
                    value="integration-test"
                ),
            ),
        ],
    )

    qdrant_results = get_qdrant_client().query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=qdrant_filter,
        limit=5,
        with_payload=True,
    ).points

    pg_ids = [row[0] for row in pg_results]
    qdrant_ids = [
        point.payload["document_id"]
        for point in qdrant_results
    ]

    assert pg_ids == [expected_id]
    assert qdrant_ids == [expected_id]
