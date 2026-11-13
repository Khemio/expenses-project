
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
 
from qdrant_client import models
from sentence_transformers import SentenceTransformer

from app.database.qdrant import get_qdrant_client
from app.database.postgres import get_connection

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "expense_documents"
DATA_FILE = Path("data/vector_documents.json")


def load_documents():
    with DATA_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def generate_embeddings(documents):
    model = SentenceTransformer(MODEL_NAME)

    texts = [document["text"] for document in documents]

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    print("Documents:", len(documents))
    print("Embedding dimensions:", embeddings.shape[1])

    return embeddings


def setup_postgres():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                ALTER TABLE vector_documents
                ADD COLUMN IF NOT EXISTS filter_group TEXT
                NOT NULL DEFAULT 'common';
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS
                vector_documents_filter_group_idx
                ON vector_documents(filter_group);
            """)

        conn.commit()

    print("PostgreSQL vector table ready.")


def setup_qdrant():
    client = get_qdrant_client()

    # Preserve an existing collection and its data.
    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=384,
                distance=models.Distance.COSINE,
            ),
        )

        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="document_type",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )

    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="filter_group",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )

    print("Qdrant collection ready.")
    return client


def store_documents(documents, embeddings):
    client = get_qdrant_client()
    now = datetime.now(timezone.utc)

    postgres_rows = []
    qdrant_points = []

    for document, embedding in zip(documents, embeddings):
        vector = embedding.tolist()

        postgres_rows.append((
            document["id"],
            document["document_type"],
            document["text"],
            document["source_id"],
            document["filter_group"],
            now,
            vector,
        ))

        qdrant_points.append(
            models.PointStruct(
                id=str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    document["id"],
                )),
                vector=vector,
                payload={
                    "document_id": document["id"],
                    "document_type": document["document_type"],
                    "content": document["text"],
                    "source_id": document["source_id"],
                    "filter_group": document["filter_group"],
                    "refreshed_at": now.isoformat(),
                },
            )
        )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO vector_documents
                (id, document_type, content, source_id,
                 filter_group, refreshed_at, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    document_type = EXCLUDED.document_type,
                    content = EXCLUDED.content,
                    source_id = EXCLUDED.source_id,
                    filter_group = EXCLUDED.filter_group,
                    refreshed_at = EXCLUDED.refreshed_at,
                    embedding = EXCLUDED.embedding;
            """, postgres_rows)

        conn.commit()

    client.upsert(
        collection_name=COLLECTION_NAME,
        points=qdrant_points,
        wait=True,
    )

    print(f"Stored {len(documents)} documents in both databases.")


if __name__ == "__main__":
    documents = load_documents()

    setup_postgres()
    setup_qdrant()

    embeddings = generate_embeddings(documents)

    store_documents(documents, embeddings)
