
import os

import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient, models

load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "expense_documents"

# QUERY = "Printer paper and pens purchased from an office supplier"
QUERY = "Can employees claim taxi rides when public transport is unavailable?"

# Generate one normalized query embedding
model = SentenceTransformer(MODEL_NAME)
query_vector = model.encode(
    QUERY,
    normalize_embeddings=True
).tolist()

# 1. Search PostgreSQL
print("\n--- PostgreSQL results ---")

with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, document_type, content,
                   embedding <=> %s::vector AS distance
            FROM vector_documents
            ORDER BY embedding <=> %s::vector
            LIMIT 5;
        """, (query_vector, query_vector))

        postgres_results = cur.fetchall()

        for row in postgres_results:
            print(f"{row[0]} | {row[1]} | distance={row[3]:.4f}")
            print(f"  {row[2]}")

# 2. Search Qdrant
print("\n--- Qdrant results ---")

client = QdrantClient(url="http://localhost:6333")

qdrant_results = client.query_points(
    collection_name=COLLECTION_NAME,
    query=query_vector,
    limit=5,
    with_payload=True,
).points

for point in qdrant_results:
    print(
        f"{point.payload['document_id']} | "
        f"{point.payload['document_type']} | "
        f"similarity={point.score:.4f}"
    )
    print(f"  {point.payload['content']}")
