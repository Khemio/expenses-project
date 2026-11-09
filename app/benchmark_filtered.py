
import os
import time

import psycopg
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from sentence_transformers import SentenceTransformer

from app.database.benchmark_queries import BENCHMARK_QUERIES

load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "expense_documents"

RARE_FILTER = Filter(
    must=[
        FieldCondition(
            key="filter_group",
            match=MatchValue(value="rare"),
        )
    ]
)


def postgres_search(conn, vector, approximate):
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("LOAD 'vector';")

            if approximate:
                cur.execute("SET LOCAL enable_seqscan = off;")
                cur.execute("SET LOCAL enable_indexscan = on;")
                cur.execute("SET LOCAL enable_bitmapscan = on;")
            else:
                cur.execute("SET LOCAL enable_indexscan = off;")
                cur.execute("SET LOCAL enable_bitmapscan = off;")

            start = time.perf_counter()

            cur.execute("""
                SELECT id
                FROM vector_documents
                WHERE filter_group = 'rare'
                ORDER BY embedding <=> %s::vector
                LIMIT 10;
            """, (vector,))

            ids = [row[0] for row in cur.fetchall()]
            latency = (time.perf_counter() - start) * 1000

            return ids, latency


def qdrant_search(client, vector, approximate):
    start = time.perf_counter()

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        query_filter=RARE_FILTER,
        limit=10,
        with_payload=True,
        search_params={"exact": not approximate},
    ).points

    latency = (time.perf_counter() - start) * 1000

    ids = [
        point.payload["document_id"]
        for point in results
    ]

    return ids, latency


def calculate_recall(exact_ids, approximate_ids):
    if not exact_ids:
        return 1.0

    return len(set(exact_ids) & set(approximate_ids)) / len(exact_ids)


def main():
    print("Loading embedding model...")
    model = SentenceTransformer(MODEL_NAME)

    qdrant = QdrantClient(url="http://localhost:6333")

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute("LOAD 'vector';")
            cur.execute("""
                SELECT COUNT(*)
                FROM vector_documents
                WHERE filter_group = 'rare';
            """)
            pg_count = cur.fetchone()[0]

    qdrant_count = qdrant.count(
        collection_name=COLLECTION_NAME,
        count_filter=RARE_FILTER,
        exact=True,
    ).count

    print(f"\nPostgreSQL rare records: {pg_count}")
    print(f"Qdrant rare records: {qdrant_count}")

    pg_recalls = []
    qd_recalls = []
    pg_exact_times = []
    pg_approx_times = []
    qd_exact_times = []
    qd_approx_times = []

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        for index, query in enumerate(BENCHMARK_QUERIES, start=1):
            vector = model.encode(
                query,
                normalize_embeddings=True,
            ).tolist()

            pg_exact, pg_exact_ms = postgres_search(
                conn, vector, approximate=False
            )
            pg_approx, pg_approx_ms = postgres_search(
                conn, vector, approximate=True
            )

            qd_exact, qd_exact_ms = qdrant_search(
                qdrant, vector, approximate=False
            )
            qd_approx, qd_approx_ms = qdrant_search(
                qdrant, vector, approximate=True
            )

            pg_recall = calculate_recall(pg_exact, pg_approx)
            qd_recall = calculate_recall(qd_exact, qd_approx)

            pg_recalls.append(pg_recall)
            qd_recalls.append(qd_recall)

            pg_exact_times.append(pg_exact_ms)
            pg_approx_times.append(pg_approx_ms)
            qd_exact_times.append(qd_exact_ms)
            qd_approx_times.append(qd_approx_ms)

            print(
                f"Query {index:02d}: "
                f"PostgreSQL recall={pg_recall:.2f}, "
                f"results={len(pg_approx)}, "
                f"Qdrant recall={qd_recall:.2f}, "
                f"results={len(qd_approx)}"
            )

    def average(values):
        return sum(values) / len(values)

    print("\n--- Filtered benchmark summary ---")
    print(f"Queries: {len(BENCHMARK_QUERIES)}")
    print(f"Filter result count: PostgreSQL={pg_count}, Qdrant={qdrant_count}")

    print("\nPostgreSQL:")
    print(f"Average filtered ANN recall@10: {average(pg_recalls):.4f}")
    print(f"Average exact latency: {average(pg_exact_times):.3f} ms")
    print(f"Average approximate latency: {average(pg_approx_times):.3f} ms")

    print("\nQdrant:")
    print(f"Average filtered ANN recall@10: {average(qd_recalls):.4f}")
    print(f"Average exact latency: {average(qd_exact_times):.3f} ms")
    print(f"Average approximate latency: {average(qd_approx_times):.3f} ms")


if __name__ == "__main__":
    main()
