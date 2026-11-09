import os
import uuid

import psycopg
from dotenv import load_dotenv
from qdrant_client import QdrantClient

load_dotenv()

COLLECTION_NAME = "expense_documents"

EXPECTED_TOTAL = 455
EXPECTED_RARE_BEFORE = 10
EXPECTED_RARE_AFTER = 23

# Choose thirteen existing MongoDB-backed receipt documents.
# This is deterministic and does not require new embeddings.
ADDITIONAL_RARE_IDS = [
    f"mongo_synthetic_receipt_{number:04d}"
    for number in range(1, 14)
]


def qdrant_point_id(document_id):
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            document_id,
        )
    )


def postgres_counts(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE filter_group = 'rare'
                ) AS rare
            FROM vector_documents
            """
        )

        return cur.fetchone()


def main():
    qdrant = QdrantClient(
        url="http://localhost:6333"
    )

    try:
        with psycopg.connect(
            os.getenv("DATABASE_URL")
        ) as conn:

            total, rare_before = postgres_counts(conn)

            print("Total documents:", total)
            print("Rare documents before:", rare_before)

            if total != EXPECTED_TOTAL:
                raise RuntimeError(
                    f"Expected {EXPECTED_TOTAL} documents, "
                    f"found {total}."
                )

            if rare_before not in (
                EXPECTED_RARE_BEFORE,
                EXPECTED_RARE_AFTER,
            ):
                raise RuntimeError(
                    f"Unexpected rare count: {rare_before}"
                )

            # Verify that every selected document exists.
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM vector_documents
                    WHERE id = ANY(%s)
                    """,
                    (ADDITIONAL_RARE_IDS,),
                )

                existing_ids = {
                    row[0]
                    for row in cur.fetchall()
                }

            if existing_ids != set(ADDITIONAL_RARE_IDS):
                missing = (
                    set(ADDITIONAL_RARE_IDS)
                    - existing_ids
                )

                raise RuntimeError(
                    f"Missing documents: {missing}"
                )

            # Update PostgreSQL metadata.
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE vector_documents
                    SET filter_group = 'rare'
                    WHERE id = ANY(%s)
                      AND filter_group <> 'rare'
                    """,
                    (ADDITIONAL_RARE_IDS,),
                )

                print(
                    "PostgreSQL rows updated:",
                    cur.rowcount,
                )

            conn.commit()

            # Update the corresponding Qdrant payloads.
            point_ids = [
                qdrant_point_id(document_id)
                for document_id in ADDITIONAL_RARE_IDS
            ]

            qdrant.set_payload(
                collection_name=COLLECTION_NAME,
                payload={"filter_group": "rare"},
                points=point_ids,
                wait=True,
            )

            print(
                "Qdrant points updated:",
                len(point_ids),
            )

            # Verify PostgreSQL.
            total, rare_after = postgres_counts(conn)

            print("\n--- PostgreSQL verification ---")
            print("Total:", total)
            print("Rare:", rare_after)
            print(
                "Rare percentage:",
                f"{rare_after / total * 100:.2f}%",
            )

            if rare_after != EXPECTED_RARE_AFTER:
                raise RuntimeError(
                    "PostgreSQL rare count is incorrect."
                )

            # Verify Qdrant using an exact payload count.
            from qdrant_client import models

            rare_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="filter_group",
                        match=models.MatchValue(
                            value="rare"
                        ),
                    )
                ]
            )

            qdrant_rare = qdrant.count(
                collection_name=COLLECTION_NAME,
                count_filter=rare_filter,
                exact=True,
            ).count

            print("\n--- Qdrant verification ---")
            print("Rare:", qdrant_rare)

            if qdrant_rare != EXPECTED_RARE_AFTER:
                raise RuntimeError(
                    "Qdrant rare count is incorrect."
                )

            print(
                "\nSUCCESS: Both databases have "
                "23 rare documents."
            )

    finally:
        qdrant.close()


if __name__ == "__main__":
    main()