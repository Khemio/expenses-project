import json
import os
import uuid
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from pymongo import MongoClient
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

load_dotenv()

DATA_FILE = Path("data/duplicate_test_cases.json")
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

COLLECTION_NAME = "expense_documents"
THRESHOLD = 0.85
TOP_K = 10


def vector_id(receipt_id):
    return f"mongo_{receipt_id}"


def qdrant_id(document_id):
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, document_id)
    )


def normalize(value):
    return value.strip().casefold()


def metadata_matches(receipt_a, receipt_b):
    """
    Compare authoritative MongoDB receipt metadata.
    """

    invoice_a = receipt_a["details"].get("invoice_number")
    invoice_b = receipt_b["details"].get("invoice_number")

    if not invoice_a or not invoice_b:
        return False

    return (
        normalize(receipt_a["vendor"])
        == normalize(receipt_b["vendor"])
        and normalize(invoice_a) == normalize(invoice_b)
        and receipt_a["country"] == receipt_b["country"]
    )


# def search_postgres(conn, embedding, excluded_document_id):
#     with conn.cursor() as cur:
#         cur.execute(
#             """
#             SELECT
#                 id,
#                 1 - (embedding <=> %s::vector) AS similarity
#             FROM vector_documents
#             WHERE document_type = 'receipt'
#               AND id LIKE 'mongo_synthetic_receipt_%%'
#               AND id <> %s
#             ORDER BY embedding <=> %s::vector
#             LIMIT %s
#             """,
#             (
#                 embedding,
#                 excluded_document_id,
#                 embedding,
#                 TOP_K,
#             ),
#         )

#         return [
#             (document_id, float(similarity))
#             for document_id, similarity in cur.fetchall()
#         ]

def search_postgres(conn, embedding, excluded_document_id):
    """
    Search PostgreSQL for similar MongoDB receipt documents.

    An optional excluded_document_id prevents self-matches.
    """

    with conn.cursor() as cur:

        # Use exact search for the initial comparison.
        cur.execute("SET LOCAL enable_indexscan = off")
        cur.execute("SET LOCAL enable_bitmapscan = off")

        cur.execute(
            """
            SELECT
                id,
                1 - (embedding <=> %s::vector) AS similarity
            FROM vector_documents
            WHERE document_type = 'receipt'
              AND id LIKE 'mongo_synthetic_receipt_%%'
              AND (%s::text IS NULL OR id <> %s::text)
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (
                embedding,
                excluded_document_id,
                excluded_document_id,
                embedding,
                TOP_K,
            ),
        )

        return [
            (document_id, float(similarity))
            for document_id, similarity in cur.fetchall()
        ]


def search_qdrant(client, embedding, excluded_document_id):
    must_not = []

    if excluded_document_id is not None:
        must_not.append(
            models.HasIdCondition(
                has_id=[qdrant_id(excluded_document_id)]
            )
        )

    result = client.query_points(
        collection_name=COLLECTION_NAME,
        query=embedding,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="document_type",
                    match=models.MatchValue(value="receipt"),
                )
            ],
            must_not=must_not,
        ),
        limit=TOP_K,
        with_payload=True,
        search_params=models.SearchParams(exact=True),
    )

    return [
        (
            point.payload["document_id"],
            float(point.score),
        )
        for point in result.points
    ]


def classify_pair(
    results,
    target_document_id,
    receipt_a,
    receipt_b,
):
    """
    A labelled pair is classified as a duplicate only
    when the candidate receipt is retrieved, exceeds
    the similarity threshold, and matches metadata.
    """

    for rank, (document_id, similarity) in enumerate(
        results, start=1
    ):
        if document_id != target_document_id:
            continue

        prediction = (
            similarity >= THRESHOLD
            and metadata_matches(receipt_a, receipt_b)
        )

        return prediction, rank, similarity

    return False, None, None


def calculate_metrics(predictions):
    tp = fp = tn = fn = 0

    for expected, predicted in predictions:
        if expected and predicted:
            tp += 1
        elif not expected and predicted:
            fp += 1
        elif not expected and not predicted:
            tn += 1
        else:
            fn += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0

    return {
        "TP": tp,
        "FP": fp,
        "TN": tn,
        "FN": fn,
        "precision": precision,
        "recall": recall,
    }


def main():
    with DATA_FILE.open("r", encoding="utf-8") as file:
        cases = json.load(file)

    assert len(cases) == 25

    mongo_client = MongoClient(os.getenv("MONGO_URI"))
    qdrant_client = QdrantClient(
        url="http://localhost:6333"
    )

    try:
        collection = mongo_client["expense_approval"]["receipts"]

        receipt_ids = {
            receipt_id
            for case in cases
            for receipt_id in (
                case["receipt_a"],
                case["receipt_b"],
            )
        }

        receipts = {
            receipt["_id"]: receipt
            for receipt in collection.find({
                "_id": {"$in": list(receipt_ids)}
            })
        }

        assert len(receipts) == len(receipt_ids), (
            "Some labelled receipts are missing from MongoDB"
        )

        model = SentenceTransformer(MODEL_NAME)

        # Text B represents the incoming receipt submission.
        query_embeddings = model.encode(
            [case["text_b"] for case in cases],
            normalize_embeddings=True,
            show_progress_bar=True,
        )

        pg_predictions = []
        qdrant_predictions = []

        with psycopg.connect(os.getenv("DATABASE_URL")) as conn:

            for case, embedding in zip(cases, query_embeddings):
                receipt_a = receipts[case["receipt_a"]]
                receipt_b = receipts[case["receipt_b"]]

                target_id = vector_id(case["receipt_a"])

                # Negative cases represent a new submission of B.
                # Exclude B's existing indexed copy to avoid
                # trivial self-retrieval.
                excluded_id = (
                    vector_id(case["receipt_b"])
                    if not case["expected_duplicate"]
                    else None
                )

                vector = embedding.tolist()

                pg_results = search_postgres(
                    conn,
                    vector,
                    excluded_id,
                )

                qdrant_results = search_qdrant(
                    qdrant_client,
                    vector,
                    excluded_id,
                )

                pg_pred, pg_rank, pg_score = classify_pair(
                    pg_results,
                    target_id,
                    receipt_a,
                    receipt_b,
                )

                qd_pred, qd_rank, qd_score = classify_pair(
                    qdrant_results,
                    target_id,
                    receipt_a,
                    receipt_b,
                )

                expected = case["expected_duplicate"]

                pg_predictions.append((expected, pg_pred))
                qdrant_predictions.append((expected, qd_pred))

                print(
                    f"{case['id']}: "
                    f"expected={expected} | "
                    f"PG={pg_pred} rank={pg_rank} "
                    f"score={pg_score} | "
                    f"Qdrant={qd_pred} rank={qd_rank} "
                    f"score={qd_score}"
                )

        for name, predictions in (
            ("PostgreSQL pgvector", pg_predictions),
            ("Qdrant", qdrant_predictions),
        ):
            metrics = calculate_metrics(predictions)

            print(f"\n--- {name} ---")
            print("TP:", metrics["TP"])
            print("FP:", metrics["FP"])
            print("TN:", metrics["TN"])
            print("FN:", metrics["FN"])
            print(f"Precision: {metrics['precision']:.4f}")
            print(f"Recall:    {metrics['recall']:.4f}")

        print("\nSUCCESS: Database-backed evaluation completed.")

    finally:
        mongo_client.close()
        qdrant_client.close()


if __name__ == "__main__":
    main()