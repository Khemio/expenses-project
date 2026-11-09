
import os

import psycopg
from dotenv import load_dotenv


load_dotenv()


def main():
    sql = """
        SELECT
            id,
            document_type,
            source_id,
            LEFT(content, 100)
        FROM vector_documents
        WHERE document_type = 'receipt'
        ORDER BY id
        LIMIT 10;
    """

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()

    print("First 10 receipt documents:")
    print("-" * 70)

    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
