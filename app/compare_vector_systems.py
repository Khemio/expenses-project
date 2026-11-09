
import os

import psycopg
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

from app.database.benchmark_queries import BENCHMARK_QUERIES

load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "expense_documents"


def main():
    model = SentenceTransformer(MODEL_NAME)
    qdrant = QdrantClient(url="http://localhost:6333")

    pg_shared_counts = []

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute("LOAD 'vector';")

        for index, query in enumerate(BENCHMARK_QUERIES, start=1):
            vector = model.encode(
                query,
                normalize_embeddings=True,
            ).tolist()

            # PostgreSQL approximate top 10
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL enable_seqscan = off;")
                    cur.execute("SET LOCAL enable_indexscan = on;")
                    cur.execute("SET LOCAL enable_bitmapscan = on;")

                    cur.execute("""
                        SELECT id
                        FROM vector_documents
                        ORDER BY embedding <=> %s::vector
                        LIMIT 10;
                    """, (vector,))

                    pg_ids = {row[0] for row in cur.fetchall()}

            # Qdrant approximate top 10
            qdrant_results = qdrant.query_points(
                collection_name=COLLECTION_NAME,
                query=vector,
                limit=10,
                with_payload=True,
            ).points

            qdrant_ids = {
                point.payload["document_id"]
                for point in qdrant_results
            }

            shared = len(pg_ids & qdrant_ids)
            pg_shared_counts.append(shared)

            print(
                f"Query {index:02d}: "
                f"shared IDs between PostgreSQL and Qdrant = "
                f"{shared}/10"
            )

    print("\n--- Cross-database comparison ---")
    print(f"Queries: {len(BENCHMARK_QUERIES)}")
    print(
        "Average shared top-10 IDs: "
        f"{sum(pg_shared_counts) / len(pg_shared_counts):.2f}/10"
    )


if __name__ == "__main__":
    main()
