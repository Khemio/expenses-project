
import os

import psycopg
from dotenv import load_dotenv
from qdrant_client import QdrantClient

load_dotenv()

COLLECTION_NAME = "expense_documents"

# Read all document IDs from PostgreSQL
with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id
            FROM vector_documents
            ORDER BY id;
        """)
        postgres_ids = {row[0] for row in cur.fetchall()}

# Read every page from Qdrant
qdrant = QdrantClient(url="http://localhost:6333")

qdrant_ids = set()
offset = None

while True:
    points, next_offset = qdrant.scroll(
        collection_name=COLLECTION_NAME,
        limit=100,
        offset=offset,
        with_payload=True,
        with_vectors=False,
    )

    for point in points:
        qdrant_ids.add(point.payload["document_id"])

    if next_offset is None:
        break

    offset = next_offset

print("PostgreSQL document count:", len(postgres_ids))
print("Qdrant document count:", len(qdrant_ids))
print("Same document IDs:", postgres_ids == qdrant_ids)

if postgres_ids != qdrant_ids:
    print("Only in PostgreSQL:", postgres_ids - qdrant_ids)
    print("Only in Qdrant:", qdrant_ids - postgres_ids)
else:
    print("SUCCESS: Both databases contain the same documents.")
