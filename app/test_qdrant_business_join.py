
import os

import psycopg
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer


load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "expense_documents"


def main():
    model = SentenceTransformer(MODEL_NAME)
    qdrant = QdrantClient(url="http://localhost:6333")

    query = (
        "Office Supplies Ltd invoice purchase of office supplies "
        "total amount EUR"
    )

    embedding = model.encode(
        query,
        normalize_embeddings=True
    ).tolist()

    # Step 1: Search Qdrant for the five closest documents.
    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=embedding,
        limit=5,
        with_payload=True
    ).points

    document_ids = [
        point.payload["document_id"]
        for point in results
    ]

    distances = {
        point.payload["document_id"]: 1 - point.score
        for point in results
    }

    if not document_ids:
        print("No documents found.")
        return

    # Step 2: Retrieve business data from PostgreSQL.
    sql = """
        SELECT
            vd.id AS document_id,
            vd.document_type,
            vd.content,
            e.id AS expense_id,
            e.description AS expense_description,
            e.amount,
            e.status,
            emp.name AS employee_name,
            cc.name AS cost_centre
        FROM vector_documents vd
        LEFT JOIN receipt_expense_mapping rem
            ON vd.id = rem.receipt_document_id
        LEFT JOIN expenses e
            ON rem.expense_id = e.id
        LEFT JOIN employees emp
            ON e.employee_id = emp.id
        LEFT JOIN cost_centres cc
            ON e.cost_centre_id = cc.id
        WHERE vd.id = ANY(%s);
    """

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (document_ids,))
            rows = cur.fetchall()

    # Step 3: Display results in Qdrant ranking order.
    row_by_id = {row[0]: row for row in rows}

    print(f"\nQuery: {query}")
    print("\nQdrant results with PostgreSQL business data:")
    print("-" * 80)

    for document_id in document_ids:
        row = row_by_id.get(document_id)

        if row is None:
            continue

        (
            document_id,
            document_type,
            content,
            expense_id,
            expense_description,
            amount,
            status,
            employee_name,
            cost_centre,
        ) = row

        print(f"Document: {document_id}")
        print(f"Type: {document_type}")
        print(f"Expense ID: {expense_id}")
        print(f"Expense: {expense_description}")
        print(f"Amount: {amount}")
        print(f"Status: {status}")
        print(f"Employee: {employee_name}")
        print(f"Cost centre: {cost_centre}")
        print(f"Qdrant distance: {distances[document_id]:.4f}")
        print(f"Content: {content[:200]}")
        print("-" * 80)


if __name__ == "__main__":
    main()
