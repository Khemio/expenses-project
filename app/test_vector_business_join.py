
import os

import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer


load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def main():
    model = SentenceTransformer(MODEL_NAME)

    # query = "office supplies receipt and expense approval policy"
    query = "Office Supplies Ltd invoice purchase of office supplies total amount EUR"

    embedding = model.encode(
        query,
        normalize_embeddings=True
    ).tolist()

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
            cc.name AS cost_centre,
            vd.embedding <=> %s::vector AS distance
        FROM vector_documents vd
        LEFT JOIN receipt_expense_mapping rem
            ON vd.id = rem.receipt_document_id
        LEFT JOIN expenses e
            ON rem.expense_id = e.id
        LEFT JOIN employees emp
            ON e.employee_id = emp.id
        LEFT JOIN cost_centres cc
            ON e.cost_centre_id = cc.id
        ORDER BY vd.embedding <=> %s::vector
        LIMIT 5;
    """

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute("LOAD 'vector';")
            cur.execute(sql, (embedding, embedding))
            rows = cur.fetchall()

    print(f"\nQuery: {query}")
    print("\nTop 5 documents with business data:")
    print("-" * 80)

    for row in rows:
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
            distance,
        ) = row

        print(f"Document: {document_id}")
        print(f"Type: {document_type}")
        print(f"Expense ID: {expense_id}")
        print(f"Expense: {expense_description}")
        print(f"Amount: {amount}")
        print(f"Status: {status}")
        print(f"Employee: {employee_name}")
        print(f"Cost centre: {cost_centre}")
        print(f"Distance: {distance:.4f}")
        print(f"Content: {content[:200]}")
        print("-" * 80)


if __name__ == "__main__":
    main()
