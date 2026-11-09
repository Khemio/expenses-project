
import time

from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

from app.database.benchmark_queries import BENCHMARK_QUERIES


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "expense_documents"


def search(client, vector, approximate=True, filter_rare=False):
    query_filter = None

    if filter_rare:
        from qdrant_client.models import (
            Filter,
            FieldCondition,
            MatchValue,
        )

        query_filter = Filter(
            must=[
                FieldCondition(
                    key="filter_group",
                    match=MatchValue(value="rare"),
                )
            ]
        )

    start = time.perf_counter()

    if approximate:
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            query_filter=query_filter,
            limit=10,
            with_payload=True,
        ).points

    else:
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            query_filter=query_filter,
            limit=10,
            with_payload=True,
            search_params={"exact": True},
        ).points

    latency_ms = (time.perf_counter() - start) * 1000

    ids = [
        point.payload["document_id"]
        for point in results
    ]

    return ids, latency_ms


def main():
    print("Loading embedding model...")

    model = SentenceTransformer(MODEL_NAME)

    client = QdrantClient(
        url="http://localhost:6333"
    )

    print("Qdrant connected.")

    exact_latencies = []
    approximate_latencies = []
    recalls = []
    shared_counts = []

    for index, query in enumerate(BENCHMARK_QUERIES, start=1):
        vector = model.encode(
            query,
            normalize_embeddings=True,
        ).tolist()

        exact_ids, exact_latency = search(
            client,
            vector,
            approximate=False,
        )

        approximate_ids, approximate_latency = search(
            client,
            vector,
            approximate=True,
        )

        shared = set(exact_ids) & set(approximate_ids)

        recall = len(shared) / 10

        exact_latencies.append(exact_latency)
        approximate_latencies.append(approximate_latency)
        recalls.append(recall)
        shared_counts.append(len(shared))

        print(
            f"Query {index:02d}: "
            f"recall@10={recall:.2f}, "
            f"shared={len(shared)}/10, "
            f"exact={exact_latency:.2f}ms, "
            f"approx={approximate_latency:.2f}ms"
        )

    print("\n--- Qdrant benchmark summary ---")
    print(f"Queries: {len(BENCHMARK_QUERIES)}")
    print(f"Average ANN recall@10: {sum(recalls) / len(recalls):.4f}")
    print(f"Average exact latency (ms): {sum(exact_latencies) / len(exact_latencies):.3f}")
    print(f"Average approximate latency (ms): {sum(approximate_latencies) / len(approximate_latencies):.3f}")
    print(f"Average shared top-10 IDs: {sum(shared_counts) / len(shared_counts):.2f}")


if __name__ == "__main__":
    main()
