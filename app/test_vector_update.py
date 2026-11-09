
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "expense_documents"
DATA_FILE = Path("data/vector_documents.json")
DOCUMENT_ID = "receipt_001"


def main():
    # Load the original source document.
    with DATA_FILE.open("r", encoding="utf-8") as file:
        documents = json.load(file)

    document = next(d for d in documents if d["id"] == DOCUMENT_ID)
    original_text = document["text"]

    client = QdrantClient(url="http://localhost:6333")
    qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_URL, DOCUMENT_ID))

    model = SentenceTransformer(MODEL_NAME)

    # Generate the original embedding.
    original_embedding = model.encode(
        original_text,
        normalize_embeddings=True,
    ).tolist()

    # Restore the original version in PostgreSQL.
    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE vector_documents
                SET content = %s,
                    embedding = %s,
                    refreshed_at = %s
                WHERE id = %s
                """,
                (
                    original_text,
                    original_embedding,
                    datetime.now(timezone.utc),
                    DOCUMENT_ID,
                ),
            )
        conn.commit()

    # Restore the original version in Qdrant.
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            models.PointStruct(
                id=qdrant_id,
                vector=original_embedding,
                payload={
                    "document_id": DOCUMENT_ID,
                    "document_type": document["document_type"],
                    "content": original_text,
                    "source_id": document["source_id"],
                    "filter_group": document["filter_group"],
                    "refreshed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        ],
        wait=True,
    )

    print("1. Original document restored in both stores.")

    # Simulate a source document change.
    updated_text = original_text + (
        " Updated source note: this receipt was reviewed "
        "and its vendor details were confirmed."
    )

    print("\n2. Source document changed.")
    print("The database copies have not been refreshed yet.")

    # Verify both stores still contain the original text.
    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM vector_documents WHERE id = %s",
                (DOCUMENT_ID,),
            )
            pg_before = cur.fetchone()[0]

    qdrant_before = client.retrieve(
        collection_name=COLLECTION_NAME,
        ids=[qdrant_id],
        with_payload=True,
        with_vectors=False,
    )[0]

    print("\n3. Before refresh:")
    print("PostgreSQL contains old text:", pg_before == original_text)
    print(
        "Qdrant contains old text:",
        qdrant_before.payload["content"] == original_text,
    )

    assert pg_before == original_text
    assert qdrant_before.payload["content"] == original_text

    # Generate an embedding for the updated text.
    updated_embedding = model.encode(
        updated_text,
        normalize_embeddings=True,
    ).tolist()

    now = datetime.now(timezone.utc)

    # Refresh PostgreSQL.
    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE vector_documents
                SET content = %s,
                    embedding = %s,
                    refreshed_at = %s
                WHERE id = %s
                """,
                (updated_text, updated_embedding, now, DOCUMENT_ID),
            )
        conn.commit()

    # Refresh Qdrant.
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            models.PointStruct(
                id=qdrant_id,
                vector=updated_embedding,
                payload={
                    "document_id": DOCUMENT_ID,
                    "document_type": document["document_type"],
                    "content": updated_text,
                    "source_id": document["source_id"],
                    "filter_group": document["filter_group"],
                    "refreshed_at": now.isoformat(),
                },
            )
        ],
        wait=True,
    )

    # Verify both stores after refresh.
    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content, refreshed_at
                FROM vector_documents
                WHERE id = %s
                """,
                (DOCUMENT_ID,),
            )
            pg_after = cur.fetchone()

    qdrant_after = client.retrieve(
        collection_name=COLLECTION_NAME,
        ids=[qdrant_id],
        with_payload=True,
        with_vectors=False,
    )[0]

    print("\n4. After refresh:")
    print("PostgreSQL updated:", pg_after[0] == updated_text)
    print(
        "Qdrant updated:",
        qdrant_after.payload["content"] == updated_text,
    )
    print("PostgreSQL refreshed_at:", pg_after[1])
    print("Qdrant refreshed_at:", qdrant_after.payload["refreshed_at"])

    assert pg_after[0] == updated_text
    assert qdrant_after.payload["content"] == updated_text

    print("\nSUCCESS: Both vector stores were refreshed successfully.")


if __name__ == "__main__":
    main()
