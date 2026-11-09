import os

import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from app.database.benchmark_queries import BENCHMARK_QUERIES

load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

QUERY = BENCHMARK_QUERIES[11]
TOP_K = 10

EF_VALUES = [40, 100, 200, 400]


def search(conn, vector, exact=False, ef=40, iterative="off"):
    with conn.transaction():
        with conn.cursor() as cur:

            if exact:
                cur.execute("SET LOCAL enable_indexscan = off")
                cur.execute("SET LOCAL enable_bitmapscan = off")
            else:
                cur.execute("SET LOCAL enable_seqscan = off")
                cur.execute("SET LOCAL enable_indexscan = on")
                # cur.execute("SET LOCAL hnsw.ef_search = %s", (ef,))
                cur.execute(
                    "SELECT set_config('hnsw.ef_search', %s, true)",
                    (str(ef),),
                )

                # Set only supported iterative scan values.
                cur.execute(
                    f"SET LOCAL hnsw.iterative_scan = '{iterative}'"
                )

            cur.execute(
                """
                SELECT
                    id,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM vector_documents
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vector, vector, TOP_K),
            )

            return [
                (document_id, float(similarity))
                for document_id, similarity in cur.fetchall()
            ]


def print_comparison(label, results, exact_ids):
    ids = {document_id for document_id, _ in results}

    overlap = len(ids & exact_ids)

    print(f"\n{label}")
    print(f"Recall@10: {overlap / TOP_K:.2f}")
    print(f"Results returned: {len(results)}")

    for rank, (document_id, score) in enumerate(
        results, start=1
    ):
        print(
            f"  {rank:2d}. "
            f"{document_id:<30} "
            f"similarity={score:.6f}"
        )


def main():
    print("Query:", QUERY)

    model = SentenceTransformer(MODEL_NAME)

    vector = model.encode(
        QUERY,
        normalize_embeddings=True,
    ).tolist()

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:

        exact_results = search(
            conn,
            vector,
            exact=True,
        )

        exact_ids = {
            document_id
            for document_id, _ in exact_results
        }

        print_comparison(
            "EXACT BASELINE",
            exact_results,
            exact_ids,
        )

        for ef in EF_VALUES:
            results = search(
                conn,
                vector,
                ef=ef,
                iterative="off",
            )

            print_comparison(
                f"HNSW ef_search={ef}, iterative=off",
                results,
                exact_ids,
            )

        for iterative in ("strict_order", "relaxed_order"):
            results = search(
                conn,
                vector,
                ef=40,
                iterative=iterative,
            )

            print_comparison(
                f"HNSW ef_search=40, iterative={iterative}",
                results,
                exact_ids,
            )


if __name__ == "__main__":
    main()