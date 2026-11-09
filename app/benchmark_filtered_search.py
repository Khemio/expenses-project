import os
from statistics import mean
from time import perf_counter

import psycopg
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

from app.database.benchmark_queries import BENCHMARK_QUERIES


load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "expense_documents"

TOP_K = 10
EXPECTED_RARE = 23

FILTER_GROUP = "rare"


def qdrant_filter():
    return models.Filter(
        must=[
            models.FieldCondition(
                key="filter_group",
                match=models.MatchValue(value=FILTER_GROUP),
            )
        ]
    )


def configure_postgres(cur, mode):
    """
    Configure a search within its own transaction.
    """

    if mode == "exact":
        cur.execute("SET LOCAL enable_indexscan = off")
        cur.execute("SET LOCAL enable_bitmapscan = off")
        return

    cur.execute("SET LOCAL enable_seqscan = off")
    cur.execute("SET LOCAL enable_indexscan = on")

    # Discourage filter-index + explicit sort plans.
    # HNSW supplies results in vector-distance order.
    cur.execute("SET LOCAL enable_sort = off")

    if mode == "hnsw_40":
        ef = 40
        iterative = "off"

    elif mode == "hnsw_40_strict":
        ef = 40
        iterative = "strict_order"

    elif mode == "hnsw_200":
        ef = 200
        iterative = "off"

    else:
        raise ValueError(f"Unknown PostgreSQL mode: {mode}")

    cur.execute(
        "SELECT set_config('hnsw.ef_search', %s, true)",
        (str(ef),),
    )

    cur.execute(
        "SELECT set_config('hnsw.iterative_scan', %s, true)",
        (iterative,),
    )


# def postgres_search(conn, vector, mode):
#     """
#     Execute one filtered query in an independent transaction.
#     """

#     with conn.transaction():
#         with conn.cursor() as cur:
#             configure_postgres(cur, mode)

#             start = perf_counter()

#             cur.execute(
#                 """
#                 SELECT id
#                 FROM vector_documents
#                 WHERE filter_group = 'rare'
#                 ORDER BY embedding <=> %s::vector
#                 LIMIT %s
#                 """,
#                 (vector, TOP_K),
#             )

#             ids = [row[0] for row in cur.fetchall()]

#             latency_ms = (perf_counter() - start) * 1000

#             return ids, latency_ms

def postgres_search(conn, vector, mode):
    """
    Execute one filtered vector query in its own transaction.

    Exact mode materializes all eligible records before
    computing vector distances, preventing accidental
    use of the HNSW index.

    Approximate modes use the configured PostgreSQL planner
    settings and HNSW index.
    """

    with conn.transaction():
        with conn.cursor() as cur:

            configure_postgres(cur, mode)

            if mode == "exact":

                query = """
                    WITH eligible AS MATERIALIZED (
                        SELECT id, embedding
                        FROM vector_documents
                        WHERE filter_group = 'rare'
                    )
                    SELECT id
                    FROM eligible
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """

            else:

                query = """
                    SELECT id
                    FROM vector_documents
                    WHERE filter_group = 'rare'
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """

            start = perf_counter()

            cur.execute(
                query,
                (vector, TOP_K),
            )

            ids = [
                row[0]
                for row in cur.fetchall()
            ]

            latency_ms = (
                perf_counter() - start
            ) * 1000

            return ids, latency_ms


def qdrant_search(client, vector, exact):
    """
    Search Qdrant using the same rare-document filter.

    Note: exact=False requests approximate search, but
    Qdrant may choose an exact scan internally when the
    filtered candidate set is very small.
    """

    params = models.SearchParams(
        exact=exact,
        hnsw_ef=40 if not exact else None,
    )

    start = perf_counter()

    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        query_filter=qdrant_filter(),
        search_params=params,
        limit=TOP_K,
        with_payload=True,
    )

    latency_ms = (perf_counter() - start) * 1000

    ids = [
        point.payload["document_id"]
        for point in response.points
    ]

    return ids, latency_ms


def recall_at_10(exact_ids, actual_ids):
    """
    ANN recall relative to exact filtered top-10.

    The denominator remains 10 even when an approximate
    search returns fewer than 10 results.
    """

    if len(exact_ids) != TOP_K:
        raise RuntimeError(
            f"Exact baseline returned {len(exact_ids)} "
            f"results instead of {TOP_K}"
        )

    return len(set(exact_ids) & set(actual_ids)) / TOP_K


def verify_filter_data(pg, qdrant):
    """
    Verify that both databases contain exactly the
    same rare document IDs before benchmarking.
    """

    with pg.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM vector_documents
            WHERE filter_group = 'rare'
            """
        )

        pg_ids = {row[0] for row in cur.fetchall()}

    qdrant_ids = set()
    offset = None

    while True:
        points, offset = qdrant.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=qdrant_filter(),
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        qdrant_ids.update(
            point.payload["document_id"]
            for point in points
        )

        if offset is None:
            break

    print("\n--- Filter verification ---")
    print("PostgreSQL rare documents:", len(pg_ids))
    print("Qdrant rare documents:", len(qdrant_ids))
    print("Same rare document IDs:", pg_ids == qdrant_ids)

    if (
        len(pg_ids) != EXPECTED_RARE
        or pg_ids != qdrant_ids
    ):
        raise RuntimeError(
            "Rare-filter data differs between databases."
        )


def verify_postgres_plan(conn, vector, mode):
    """
    Confirm which PostgreSQL access path is actually used.
    """

    with conn.transaction():
        with conn.cursor() as cur:
            configure_postgres(cur, mode)

            # cur.execute(
            #     """
            #     EXPLAIN
            #     SELECT id
            #     FROM vector_documents
            #     WHERE filter_group = 'rare'
            #     ORDER BY embedding <=> %s::vector
            #     LIMIT %s
            #     """,
            #     (vector, TOP_K),
            # )

            if mode == "exact":
                query = """
                    EXPLAIN
                    WITH eligible AS MATERIALIZED (
                        SELECT id, embedding
                        FROM vector_documents
                        WHERE filter_group = 'rare'
                    )
                    SELECT id
                    FROM eligible
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """
            else:
                query = """
                    EXPLAIN
                    SELECT id
                    FROM vector_documents
                    WHERE filter_group = 'rare'
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """

            cur.execute(
                query,
                (vector, TOP_K),
            )

            plan = "\n".join(
                row[0] for row in cur.fetchall()
            )

    print(f"\n--- PostgreSQL plan: {mode} ---")

    # Avoid printing the entire 384-dimensional vector.
    for line in plan.splitlines():
        if "Order By:" in line:
            print("  Order By: cosine distance")
        else:
            print(line)

    uses_hnsw = (
        "vector_documents_embedding_hnsw" in plan
    )

    if mode == "exact" and uses_hnsw:
        raise RuntimeError(
            "Exact baseline unexpectedly used HNSW."
        )

    if mode != "exact" and not uses_hnsw:
        raise RuntimeError(
            f"Expected HNSW index for mode {mode}."
        )


def summarize(name, observations):
    recalls = [
        observation["recall"]
        for observation in observations
    ]

    latencies = [
        observation["latency_ms"]
        for observation in observations
    ]

    counts = [
        observation["returned"]
        for observation in observations
    ]

    missing_queries = [
        index
        for index, observation in enumerate(
            observations,
            start=1,
        )
        if observation["recall"] < 1.0
    ]

    short_queries = [
        index
        for index, count in enumerate(
            counts,
            start=1,
        )
        if count < TOP_K
    ]

    print(f"\n{name}")
    print(f"  Mean recall@10: {mean(recalls):.4f}")
    print(f"  Mean latency:   {mean(latencies):.3f} ms")
    print(f"  Mean returned:  {mean(counts):.2f}/10")

    print(
        "  Queries with imperfect recall:",
        missing_queries,
    )

    print(
        "  Queries returning fewer than 10:",
        short_queries,
    )


def main():
    print("Loading embedding model...")

    model = SentenceTransformer(MODEL_NAME)

    embeddings = model.encode(
        BENCHMARK_QUERIES,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    vectors = [
        embedding.tolist()
        for embedding in embeddings
    ]

    print("Queries:", len(vectors))
    print("Top K:", TOP_K)
    print("Filter:", FILTER_GROUP)

    qdrant = QdrantClient(
        url="http://localhost:6333"
    )

    pg_modes = [
        "exact",
        "hnsw_40",
        "hnsw_40_strict",
        "hnsw_200",
    ]

    results = {
        "PostgreSQL exact": [],
        "PostgreSQL HNSW ef=40": [],
        "PostgreSQL HNSW ef=40 strict": [],
        "PostgreSQL HNSW ef=200": [],
        "Qdrant exact": [],
        "Qdrant hnsw_ef=40": [],
    }

    try:
        # with psycopg.connect(
        #     os.getenv("DATABASE_URL"),
        #     autocommit=True,
        # ) as pg:
        with psycopg.connect(
            os.getenv("DATABASE_URL"),
            autocommit=True,
            prepare_threshold=None,
        ) as pg:

            verify_filter_data(pg, qdrant)

            # Verify PostgreSQL execution strategies.
            for mode in pg_modes:
                verify_postgres_plan(
                    pg,
                    vectors[0],
                    mode,
                )

            for index, vector in enumerate(
                vectors,
                start=1,
            ):

                # Exact ground truth for PostgreSQL.
                pg_exact, pg_exact_ms = postgres_search(
                    pg,
                    vector,
                    "exact",
                )

                # Exact ground truth for Qdrant.
                qd_exact, qd_exact_ms = qdrant_search(
                    qdrant,
                    vector,
                    exact=True,
                )

                print(
                    f"\nQuery {index:02d} exact baseline:"
                )
                print(
                    f"  PostgreSQL: {len(pg_exact)} results"
                )
                print(
                    f"  Qdrant:     {len(qd_exact)} results"
                )

                if len(pg_exact) != TOP_K or len(qd_exact) != TOP_K:
                    print("\nINCOMPLETE EXACT BASELINE")
                    print("Query:", BENCHMARK_QUERIES[index - 1])
                    print("PostgreSQL IDs:", pg_exact)
                    print("Qdrant IDs:", qd_exact)

                    raise RuntimeError(
                        "An exact-search baseline returned "
                        "fewer than ten documents."
                    )

                # Cross-database exact consistency.
                shared_exact = len(
                    set(pg_exact) & set(qd_exact)
                )

                pg_observations = [
                    (
                        "PostgreSQL exact",
                        pg_exact,
                        pg_exact_ms,
                    )
                ]

                for mode, label in (
                    ("hnsw_40", "PostgreSQL HNSW ef=40"),
                    (
                        "hnsw_40_strict",
                        "PostgreSQL HNSW ef=40 strict",
                    ),
                    ("hnsw_200", "PostgreSQL HNSW ef=200"),
                ):
                    ids, latency = postgres_search(
                        pg,
                        vector,
                        mode,
                    )

                    pg_observations.append(
                        (label, ids, latency)
                    )

                for label, ids, latency in pg_observations:
                    results[label].append(
                        {
                            "recall": recall_at_10(
                                pg_exact,
                                ids,
                            ),
                            "latency_ms": latency,
                            "returned": len(ids),
                        }
                    )

                # Qdrant approximate-search request.
                qd_approx, qd_approx_ms = qdrant_search(
                    qdrant,
                    vector,
                    exact=False,
                )

                for label, ids, latency in (
                    ("Qdrant exact", qd_exact, qd_exact_ms),
                    (
                        "Qdrant hnsw_ef=40",
                        qd_approx,
                        qd_approx_ms,
                    ),
                ):
                    results[label].append(
                        {
                            "recall": recall_at_10(
                                qd_exact,
                                ids,
                            ),
                            "latency_ms": latency,
                            "returned": len(ids),
                        }
                    )

                print(
                    f"Query {index:02d}: "
                    f"PG exact={len(pg_exact)}, "
                    f"Qdrant exact={len(qd_exact)}, "
                    f"shared exact={shared_exact}/10"
                )

                if shared_exact < TOP_K:
                    print(
                        "  WARNING: Exact result sets differ!"
                    )
                    print(
                        "  PostgreSQL:",
                        pg_exact,
                    )
                    print(
                        "  Qdrant:",
                        qd_exact,
                    )

    finally:
        qdrant.close()

    print("\n" + "=" * 65)
    print("FILTERED VECTOR SEARCH BENCHMARK")
    print("=" * 65)

    print("Filter selectivity: 23/455 = 5.05%")
    print("Queries:", len(vectors))
    print("Top K:", TOP_K)

    for name, observations in results.items():
        summarize(name, observations)

    print(
        "\nSUCCESS: Filtered-search benchmark completed."
    )


if __name__ == "__main__":
    main()