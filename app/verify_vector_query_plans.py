import os

import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from app.database.benchmark_queries import BENCHMARK_QUERIES

load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

QUERY = BENCHMARK_QUERIES[11]  # Query 12


def explain_query(conn, vector, exact):
    """
    Run EXPLAIN with transaction-local settings.

    Requires a connection with autocommit=True.
    """

    with conn.transaction():
        with conn.cursor() as cur:

            if exact:
                cur.execute("SET LOCAL enable_indexscan = off")
                cur.execute("SET LOCAL enable_bitmapscan = off")

            else:
                cur.execute("SET LOCAL enable_seqscan = off")
                cur.execute("SET LOCAL enable_indexscan = on")

                cur.execute(
                    "SELECT set_config('hnsw.ef_search', %s, true)",
                    ("40",),
                )

                cur.execute(
                    "SELECT set_config('hnsw.iterative_scan', %s, true)",
                    ("off",),
                )

            cur.execute(
                """
                EXPLAIN (ANALYZE, BUFFERS)
                SELECT id
                FROM vector_documents
                ORDER BY embedding <=> %s::vector
                LIMIT 10
                """,
                (vector,),
            )

            return [row[0] for row in cur.fetchall()]


def main():
    print("Query:", QUERY)

    model = SentenceTransformer(MODEL_NAME)

    vector = model.encode(
        QUERY,
        normalize_embeddings=True,
    ).tolist()

    with psycopg.connect(
        os.getenv("DATABASE_URL"),
        autocommit=True,
    ) as conn:

        print("\n=== EXACT SEARCH ===")

        exact_plan = explain_query(
            conn,
            vector,
            exact=True,
        )

        for line in exact_plan:
            print(line)

        print("\n=== HNSW SEARCH ===")

        approximate_plan = explain_query(
            conn,
            vector,
            exact=False,
        )

        for line in approximate_plan:
            print(line)

        print("\n=== VERIFICATION ===")

        exact_uses_seqscan = any(
            "Seq Scan on vector_documents" in line
            for line in exact_plan
        )

        approx_uses_hnsw = any(
            "vector_documents_embedding_hnsw" in line
            for line in approximate_plan
        )

        print(
            "Exact search uses sequential scan:",
            exact_uses_seqscan,
        )

        print(
            "Approximate search uses HNSW index:",
            approx_uses_hnsw,
        )

        if not exact_uses_seqscan or not approx_uses_hnsw:
            raise RuntimeError(
                "One or more query plans differ from expectations."
            )

        print("\nSUCCESS: Search execution plans verified.")


if __name__ == "__main__":
    main()