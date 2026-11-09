import os
from statistics import mean
from time import perf_counter

import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from app.database.benchmark_queries import BENCHMARK_QUERIES

load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

TOP_K = 10


def main():
    model = SentenceTransformer(MODEL_NAME)

    embeddings = model.encode(
        BENCHMARK_QUERIES,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    latencies = []

    with psycopg.connect(
        os.getenv("DATABASE_URL"),
        autocommit=True,
        prepare_threshold=None,
    ) as conn:

        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM vector_documents
                WHERE filter_group = 'rare'
            """)

            rare_count = cur.fetchone()[0]

        print("Rare documents:", rare_count)

        assert rare_count == 23

        for index, embedding in enumerate(
            embeddings,
            start=1,
        ):
            vector = embedding.tolist()

            with conn.transaction():
                with conn.cursor() as cur:

                    # Do not force any particular index.
                    # Let PostgreSQL choose its preferred plan.

                    start = perf_counter()

                    cur.execute(
                        """
                        SELECT id
                        FROM vector_documents
                        WHERE filter_group = 'rare'
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (vector, TOP_K),
                    )

                    ids = [
                        row[0]
                        for row in cur.fetchall()
                    ]

                    elapsed_ms = (
                        perf_counter() - start
                    ) * 1000

                    latencies.append(elapsed_ms)

                    if len(ids) != TOP_K:
                        raise RuntimeError(
                            f"Query {index} returned "
                            f"{len(ids)} results"
                        )

                    print(
                        f"Query {index:02d}: "
                        f"{len(ids)} results, "
                        f"{elapsed_ms:.3f} ms"
                    )

        print("\n--- Filter-first benchmark ---")

        print(
            f"Average latency: "
            f"{mean(latencies):.3f} ms"
        )

        print(
            "All queries returned 10 results: True"
        )

        # Inspect the natural execution plan.
        with conn.cursor() as cur:
            cur.execute(
                """
                EXPLAIN (FORMAT JSON)
                SELECT id
                FROM vector_documents
                WHERE filter_group = 'rare'
                ORDER BY embedding <=> %s::vector
                LIMIT 10
                """,
                (embeddings[0].tolist(),),
            )

            plan = cur.fetchone()[0][0]["Plan"]

        def print_plan(node, depth=0):
            print(
                "  " * depth
                + node["Node Type"]
                + (
                    " using " + node["Index Name"]
                    if "Index Name" in node
                    else ""
                )
            )

            for child in node.get("Plans", []):
                print_plan(child, depth + 1)

        print("\nNatural PostgreSQL execution plan:")
        print_plan(plan)

    print(
        "\nSUCCESS: Filter-first benchmark completed."
    )


if __name__ == "__main__":
    main()