import json
import os
import re
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

load_dotenv()

DATA_FILE = Path("data/policy_test_cases.json")

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "expense_documents"

TOP_K = 5

# There are 100 policy documents representing 20 unique passages.
# Retrieve all policy documents so duplicate copies cannot hide
# relevant groups beyond a small raw result limit.
SEARCH_LIMIT = 100


def canonical_policy_id(document_id):
    """
    Convert repeated policy document IDs to their canonical group.

    Examples:
        policy_001 -> policy_001
        policy_021 -> policy_001
        policy_041 -> policy_001
        policy_082 -> policy_002
    """

    match = re.fullmatch(r"policy_(\d{3})", document_id)

    if match is None:
        raise ValueError(
            f"Unexpected policy document ID: {document_id}"
        )

    number = int(match.group(1))

    if not 1 <= number <= 100:
        raise ValueError(
            f"Policy number out of range: {number}"
        )

    canonical_number = ((number - 1) % 20) + 1

    return f"policy_{canonical_number:03d}"


def deduplicate_policy_groups(document_ids):
    """
    Preserve the original search ranking while keeping
    only the first occurrence of each policy group.
    """

    seen = set()
    groups = []

    for document_id in document_ids:
        group_id = canonical_policy_id(document_id)

        if group_id in seen:
            continue

        seen.add(group_id)
        groups.append(group_id)

    return groups


def search_postgres(conn, embedding):
    """
    Exact cosine-distance search in PostgreSQL.
    """

    with conn.cursor() as cur:
        cur.execute(
            "SET LOCAL enable_indexscan = off"
        )

        cur.execute(
            "SET LOCAL enable_bitmapscan = off"
        )

        cur.execute(
            """
            SELECT id
            FROM vector_documents
            WHERE document_type = 'policy'
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (
                embedding,
                SEARCH_LIMIT,
            ),
        )

        return [row[0] for row in cur.fetchall()]


def search_qdrant(client, embedding):
    """
    Exact cosine search in Qdrant, filtered to policies.
    """

    result = client.query_points(
        collection_name=COLLECTION_NAME,
        query=embedding,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="document_type",
                    match=models.MatchValue(
                        value="policy"
                    ),
                )
            ]
        ),
        search_params=models.SearchParams(
            exact=True
        ),
        limit=SEARCH_LIMIT,
        with_payload=True,
    )

    return [
        point.payload["document_id"]
        for point in result.points
    ]


def evaluate_ranking(ranked_groups, relevant_ids):
    """
    Return recall@5 and reciprocal rank.

    Recall@5 is calculated over the first five
    distinct policy groups.

    Reciprocal rank uses the first relevant group
    in the full deduplicated ranking.
    """

    relevant = set(relevant_ids)

    top_five = ranked_groups[:TOP_K]

    retrieved_relevant = relevant.intersection(top_five)

    recall_at_5 = len(retrieved_relevant) / len(relevant)

    reciprocal_rank = 0.0

    for rank, group_id in enumerate(
        ranked_groups,
        start=1,
    ):
        if group_id in relevant:
            reciprocal_rank = 1.0 / rank
            break

    return recall_at_5, reciprocal_rank


def main():
    with DATA_FILE.open("r", encoding="utf-8") as file:
        cases = json.load(file)

    assert len(cases) == 20

    model = SentenceTransformer(MODEL_NAME)

    print("Generating query embeddings...")

    embeddings = model.encode(
        [case["query"] for case in cases],
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    qdrant_client = QdrantClient(
        url="http://localhost:6333"
    )

    pg_recalls = []
    pg_reciprocal_ranks = []

    qdrant_recalls = []
    qdrant_reciprocal_ranks = []

    try:
        with psycopg.connect(
            os.getenv("DATABASE_URL")
        ) as conn:

            for case, embedding in zip(cases, embeddings):
                vector = embedding.tolist()

                expected = case["relevant_policy_ids"]

                # Search both databases.
                pg_document_ids = search_postgres(
                    conn,
                    vector,
                )

                qdrant_document_ids = search_qdrant(
                    qdrant_client,
                    vector,
                )

                # Convert document IDs to unique policy groups.
                pg_groups = deduplicate_policy_groups(
                    pg_document_ids
                )

                qdrant_groups = deduplicate_policy_groups(
                    qdrant_document_ids
                )

                # Evaluate relevance.
                pg_recall, pg_rr = evaluate_ranking(
                    pg_groups,
                    expected,
                )

                qdrant_recall, qdrant_rr = evaluate_ranking(
                    qdrant_groups,
                    expected,
                )

                pg_recalls.append(pg_recall)
                pg_reciprocal_ranks.append(pg_rr)

                qdrant_recalls.append(qdrant_recall)
                qdrant_reciprocal_ranks.append(qdrant_rr)

                print(f"\n{case['id']}: {case['query']}")
                print("Relevant:", expected)

                print(
                    "PostgreSQL top 5:",
                    pg_groups[:TOP_K],
                )
                print(
                    f"  Recall@5={pg_recall:.2f}, "
                    f"RR={pg_rr:.4f}"
                )

                print(
                    "Qdrant top 5:",
                    qdrant_groups[:TOP_K],
                )
                print(
                    f"  Recall@5={qdrant_recall:.2f}, "
                    f"RR={qdrant_rr:.4f}"
                )

    finally:
        qdrant_client.close()

    # Aggregate metrics.
    n = len(cases)

    pg_average_recall = sum(pg_recalls) / n
    pg_mrr = sum(pg_reciprocal_ranks) / n

    qdrant_average_recall = sum(qdrant_recalls) / n
    qdrant_mrr = sum(qdrant_reciprocal_ranks) / n

    print("\n" + "=" * 60)
    print("POLICY RETRIEVAL EVALUATION")
    print("=" * 60)

    print("Queries:", n)
    print("Top K:", TOP_K)
    print("Search mode: Exact")
    print("Evaluation unit: Unique policy groups")

    print("\nPostgreSQL pgvector:")
    print(f"  Mean recall@5: {pg_average_recall:.4f}")
    print(f"  MRR:           {pg_mrr:.4f}")

    print("\nQdrant:")
    print(f"  Mean recall@5: {qdrant_average_recall:.4f}")
    print(f"  MRR:           {qdrant_mrr:.4f}")

    print(
        "\nSUCCESS: Policy retrieval evaluation completed."
    )


if __name__ == "__main__":
    main()