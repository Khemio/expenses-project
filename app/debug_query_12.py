import os
import re

import psycopg
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

from app.database.benchmark_queries import BENCHMARK_QUERIES

load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "expense_documents"

QUERY_INDEX = 11  # Zero-based index: Query 12
TOP_K = 10


def policy_group(document_id):
    match = re.fullmatch(r"policy_(\d{3})", document_id)

    if not match:
        return "-"

    number = int(match.group(1))
    canonical = ((number - 1) % 20) + 1

    return f"policy_{canonical:03d}"


def print_results(title, results):
    print(f"\n--- {title} ---")

    for rank, (document_id, score, content) in enumerate(
        results, start=1
    ):
        print(
            f"{rank:2d}. "
            f"id={document_id:<30} "
            f"group={policy_group(document_id):<12} "
            f"similarity={score:.8f}"
        )
        print(f"    {content[:140]}")


def search_postgres(conn, vector):
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET LOCAL enable_indexscan = off")
            cur.execute("SET LOCAL enable_bitmapscan = off")

            cur.execute(
                """
                SELECT
                    id,
                    1 - (embedding <=> %s::vector) AS similarity,
                    content
                FROM vector_documents
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vector, vector, TOP_K),
            )

            return [
                (document_id, float(score), content)
                for document_id, score, content in cur.fetchall()
            ]


def search_qdrant(client, vector):
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=TOP_K,
        with_payload=True,
        search_params=models.SearchParams(exact=True),
    )

    return [
        (
            point.payload["document_id"],
            float(point.score),
            point.payload.get("content", ""),
        )
        for point in response.points
    ]

def search_postgres_approx(conn, vector):
    """
    PostgreSQL HNSW search with the same settings
    used by the cross-database benchmark.
    """

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET LOCAL enable_seqscan = off")
            cur.execute("SET LOCAL enable_indexscan = on")
            cur.execute("SET LOCAL enable_bitmapscan = on")
            cur.execute("SET LOCAL hnsw.ef_search = 40")

            cur.execute(
                """
                SELECT
                    id,
                    1 - (embedding <=> %s::vector) AS similarity,
                    content
                FROM vector_documents
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vector, vector, TOP_K),
            )

            return [
                (document_id, float(score), content)
                for document_id, score, content in cur.fetchall()
            ]


def search_qdrant_approx(client, vector):
    """
    Qdrant approximate HNSW search.

    Set hnsw_ef explicitly so the benchmark
    records its search configuration.
    """

    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=TOP_K,
        with_payload=True,
        search_params=models.SearchParams(
            exact=False,
            hnsw_ef=40,
        ),
    )

    return [
        (
            point.payload["document_id"],
            float(point.score),
            point.payload.get("content", ""),
        )
        for point in response.points
    ]

def main():
    query = BENCHMARK_QUERIES[QUERY_INDEX]

    print("Query number:", QUERY_INDEX + 1)
    print("Query:", query)

    model = SentenceTransformer(MODEL_NAME)

    vector = model.encode(
        query,
        normalize_embeddings=True,
    ).tolist()

    qdrant = QdrantClient(url="http://localhost:6333")

    try:
        with psycopg.connect(
            os.getenv("DATABASE_URL")
        ) as conn:

            pg_exact = search_postgres(conn, vector)
            pg_approx = search_postgres_approx(conn, vector)

        qdrant_exact = search_qdrant(qdrant, vector)
        qdrant_approx = search_qdrant_approx(qdrant, vector)

        print_results("PostgreSQL exact", pg_exact)
        print_results("PostgreSQL HNSW", pg_approx)

        print_results("Qdrant exact", qdrant_exact)
        print_results("Qdrant HNSW", qdrant_approx)

        def ids(results):
            return {row[0] for row in results}

        print("\n--- Comparison ---")

        print(
            "PostgreSQL exact vs HNSW:",
            len(ids(pg_exact) & ids(pg_approx)),
            "/10",
        )

        print(
            "Qdrant exact vs HNSW:",
            len(ids(qdrant_exact) & ids(qdrant_approx)),
            "/10",
        )

        print(
            "Cross-database exact:",
            len(ids(pg_exact) & ids(qdrant_exact)),
            "/10",
        )

        print(
            "Cross-database HNSW:",
            len(ids(pg_approx) & ids(qdrant_approx)),
            "/10",
        )

    finally:
        qdrant.close()


if __name__ == "__main__":
    main()