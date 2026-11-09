import os

import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def main():
    model = SentenceTransformer(MODEL_NAME)

    query_text = (
        "Invoice HU-SYN-00001 issued by Danube Business Supplies. "
        "Date: 2026-01-01. Amount payable: 100.00 EUR."
    )

    embedding = model.encode(
        query_text,
        normalize_embeddings=True,
    ).tolist()

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:

            print("\n=== 1. DOCUMENT COUNTS ===")

            cur.execute("""
                SELECT document_type, COUNT(*)
                FROM vector_documents
                GROUP BY document_type
                ORDER BY document_type
            """)

            for row in cur.fetchall():
                print(row)

            print("\n=== 2. MONGODB DOCUMENT COUNT ===")

            cur.execute("""
                SELECT COUNT(*)
                FROM vector_documents
                WHERE id LIKE 'mongo_synthetic_receipt_%'
            """)

            print("Matching documents:", cur.fetchone()[0])

            print("\n=== 3. SAMPLE DOCUMENTS ===")

            cur.execute("""
                SELECT id, document_type, source_id
                FROM vector_documents
                WHERE id LIKE 'mongo_synthetic_receipt_%'
                ORDER BY id
                LIMIT 5
            """)

            for row in cur.fetchall():
                print(row)

            print("\n=== 4. TARGET DOCUMENT ===")

            cur.execute("""
                SELECT id, document_type, content
                FROM vector_documents
                WHERE id = 'mongo_synthetic_receipt_0001'
            """)

            print(cur.fetchone())

            print("\n=== 5. FILTERED VECTOR SEARCH ===")

            cur.execute("SET LOCAL enable_indexscan = off")
            cur.execute("SET LOCAL enable_bitmapscan = off")

            cur.execute("""
                SELECT
                    id,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM vector_documents
                WHERE document_type = 'receipt'
                  AND id LIKE 'mongo_synthetic_receipt_%%'
                ORDER BY embedding <=> %s::vector
                LIMIT 10
            """, (embedding, embedding))

            for row in cur.fetchall():
                print(row)

            print("\n=== 6. QUERY PLAN ===")

            cur.execute("""
                EXPLAIN
                SELECT id
                FROM vector_documents
                WHERE document_type = 'receipt'
                  AND id LIKE 'mongo_synthetic_receipt_%%'
                ORDER BY embedding <=> %s::vector
                LIMIT 10
            """, (embedding,))

            for row in cur.fetchall():
                print(row[0])


if __name__ == "__main__":
    main()