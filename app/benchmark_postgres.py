
import os
import time

import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from app.database.benchmark_queries import BENCHMARK_QUERIES

load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL = SentenceTransformer(MODEL_NAME)


def embed_query(query):
    return MODEL.encode(
        query,
        normalize_embeddings=True,
    ).tolist()


# def search(conn, vector, approximate=True, filter_rare=False):
#     with conn.cursor() as cur:
#         if approximate:
#             cur.execute("SET LOCAL enable_seqscan = off;")
#             cur.execute("SET LOCAL enable_indexscan = on;")
#             cur.execute("SET LOCAL enable_bitmapscan = on;")
#         else:
#             # Disable index scans to obtain exact nearest neighbours.
#             cur.execute("SET LOCAL enable_indexscan = off;")
#             cur.execute("SET LOCAL enable_bitmapscan = off;")

#         filter_sql = (
#             "WHERE filter_group = 'rare'"
#             if filter_rare
#             else ""
#         )

#         sql = f"""
#             SELECT id
#             FROM vector_documents
#             {filter_sql}
#             ORDER BY embedding <=> %s::vector
#             LIMIT 10;
#         """

#         start = time.perf_counter()

#         cur.execute(sql, (vector,))
#         results = [row[0] for row in cur.fetchall()]

#         latency_ms = (time.perf_counter() - start) * 1000

#         return results, latency_ms

def search(conn, vector, approximate=True, filter_rare=False, show_plan=False):
    with conn.cursor() as cur:
        if approximate:
            cur.execute("SET LOCAL enable_seqscan = off;")
            cur.execute("SET LOCAL enable_indexscan = on;")
            cur.execute("SET LOCAL enable_bitmapscan = on;")
        else:
            # Disable index scans to obtain exact nearest neighbours.
            cur.execute("SET LOCAL enable_indexscan = off;")
            cur.execute("SET LOCAL enable_bitmapscan = off;")

        filter_sql = (
            "WHERE filter_group = 'rare'"
            if filter_rare
            else ""
        )

        sql = f"""
            SELECT id
            FROM vector_documents
            {filter_sql}
            ORDER BY embedding <=> %s::vector
            LIMIT 10;
        """

        # Optional diagnostic: inspect the query plan.
        if show_plan:
            cur.execute("EXPLAIN (COSTS OFF) " + sql, (vector,))
            print("\n--- PostgreSQL query plan ---")
            for row in cur.fetchall():
                print(row[0])

        start = time.perf_counter()

        cur.execute(sql, (vector,))
        results = [row[0] for row in cur.fetchall()]

        latency_ms = (time.perf_counter() - start) * 1000

        return results, latency_ms


def main():
    exact_recalls = []
    approximate_latencies = []
    exact_latencies = []
    shared_top10 = []

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("LOAD 'vector';")
                cur.execute("SHOW hnsw.ef_search;")
                ef_search = cur.fetchone()[0]

                cur.execute("SHOW hnsw.iterative_scan;")
                iterative_scan = cur.fetchone()[0]

        print("HNSW ef_search:", ef_search)
        print("HNSW iterative_scan:", iterative_scan)

        for number, query in enumerate(BENCHMARK_QUERIES, start=1):
            vector = embed_query(query)

            with conn.transaction():
                exact_ids, exact_ms = search(
                    conn, vector, approximate=False
                )

            with conn.transaction():

                approximate_ids, approximate_ms = search(
                    conn, vector, approximate=True, show_plan=True
                )

            shared = len(set(exact_ids) & set(approximate_ids))
            recall = shared / 10

            exact_recalls.append(recall)
            exact_latencies.append(exact_ms)
            approximate_latencies.append(approximate_ms)
            shared_top10.append(shared)

            print(
                f"Query {number:02d}: "
                f"recall@10={recall:.2f}, "
                f"shared={shared}/10, "
                f"exact={exact_ms:.2f}ms, "
                f"approx={approximate_ms:.2f}ms"
            )

    print("\n--- PostgreSQL benchmark summary ---")
    print("Queries:", len(BENCHMARK_QUERIES))
    print(
        "Average ANN recall@10:",
        f"{sum(exact_recalls) / len(exact_recalls):.4f}",
    )
    print(
        "Average exact latency (ms):",
        f"{sum(exact_latencies) / len(exact_latencies):.3f}",
    )
    print(
        "Average approximate latency (ms):",
        f"{sum(approximate_latencies) / len(approximate_latencies):.3f}",
    )
    print(
        "Average shared top-10 IDs:",
        f"{sum(shared_top10) / len(shared_top10):.2f}",
    )


if __name__ == "__main__":
    main()
