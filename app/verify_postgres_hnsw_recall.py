import os
from time import perf_counter

import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from app.database.benchmark_queries import BENCHMARK_QUERIES

load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

TOP_K = 10
EF_VALUES = [40, 100, 200, 400]


def search(conn, vector, *, exact=False, ef=40):
    """
    Execute each search in its own top-level transaction.

    The connection must use autocommit=True.
    """

    with conn.transaction():
        with conn.cursor() as cur:

            if exact:
                cur.execute(
                    "SET LOCAL enable_indexscan = off"
                )
                cur.execute(
                    "SET LOCAL enable_bitmapscan = off"
                )
            else:
                cur.execute(
                    "SET LOCAL enable_seqscan = off"
                )
                cur.execute(
                    "SET LOCAL enable_indexscan = on"
                )

                cur.execute(
                    """
                    SELECT set_config(
                        'hnsw.ef_search',
                        %s,
                        true
                    )
                    """,
                    (str(ef),),
                )

                cur.execute(
                    """
                    SELECT set_config(
                        'hnsw.iterative_scan',
                        'off',
                        true
                    )
                    """
                )

            start = perf_counter()

            cur.execute(
                """
                SELECT id
                FROM vector_documents
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vector, TOP_K),
            )

            ids = [row[0] for row in cur.fetchall()]

            elapsed_ms = (
                perf_counter() - start
            ) * 1000

            return ids, elapsed_ms


def recall_at_k(exact_ids, approximate_ids):
    """
    Compare approximate results to the exact top K.
    """

    return (
        len(set(exact_ids) & set(approximate_ids))
        / len(exact_ids)
    )


def main():
    print("Loading embedding model...")

    model = SentenceTransformer(MODEL_NAME)

    embeddings = model.encode(
        BENCHMARK_QUERIES,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    # Important: avoid persistent implicit transactions.
    with psycopg.connect(
        os.getenv("DATABASE_URL"),
        autocommit=True,
    ) as conn:

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM vector_documents"
            )

            count = cur.fetchone()[0]

        print("Total vector documents:", count)
        print("Total queries:", len(BENCHMARK_QUERIES))

        # Establish exact ground truth first.
        exact_results = []

        for vector in embeddings:
            ids, elapsed = search(
                conn,
                vector.tolist(),
                exact=True,
            )

            exact_results.append((ids, elapsed))

        exact_average_ms = (
            sum(elapsed for _, elapsed in exact_results)
            / len(exact_results)
        )

        print(
            f"\nExact average latency: "
            f"{exact_average_ms:.3f} ms"
        )

        # Compare HNSW configurations.
        for ef in EF_VALUES:

            recalls = []
            latencies = []

            print(f"\n--- HNSW ef_search={ef} ---")

            for index, vector in enumerate(
                embeddings,
                start=1,
            ):
                expected_ids = exact_results[index - 1][0]

                actual_ids, elapsed = search(
                    conn,
                    vector.tolist(),
                    exact=False,
                    ef=ef,
                )

                recall = recall_at_k(
                    expected_ids,
                    actual_ids,
                )

                recalls.append(recall)
                latencies.append(elapsed)

                print(
                    f"Query {index:02d}: "
                    f"recall@10={recall:.2f} "
                    f"latency={elapsed:.2f}ms"
                )

            average_recall = sum(recalls) / len(recalls)

            average_latency = (
                sum(latencies) / len(latencies)
            )

            print(f"\nSummary ef_search={ef}")
            print(
                f"Mean recall@10: "
                f"{average_recall:.4f}"
            )
            print(
                f"Mean latency:   "
                f"{average_latency:.3f} ms"
            )

            failures = [
                index
                for index, recall in enumerate(
                    recalls,
                    start=1,
                )
                if recall < 1.0
            ]

            print("Queries with imperfect recall:", failures)

    print("\nSUCCESS: PostgreSQL recall verification completed.")


if __name__ == "__main__":
    main()