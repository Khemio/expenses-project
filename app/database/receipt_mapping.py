
import os

import psycopg
from dotenv import load_dotenv


load_dotenv()


def main():
    sql = """
        CREATE TABLE IF NOT EXISTS receipt_expense_mapping (
            receipt_document_id TEXT PRIMARY KEY,
            expense_id INTEGER NOT NULL REFERENCES expenses(id),
            mapping_note TEXT NOT NULL
        );

        INSERT INTO receipt_expense_mapping (
            receipt_document_id,
            expense_id,
            mapping_note
        )
        VALUES
            (
                'receipt_001',
                5,
                'Synthetic demonstration mapping: IT equipment'
            ),
            (
                'receipt_002',
                6,
                'Synthetic demonstration mapping: IT software'
            )
        ON CONFLICT (receipt_document_id)
        DO UPDATE SET
            expense_id = EXCLUDED.expense_id,
            mapping_note = EXCLUDED.mapping_note;
    """

    with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)

    print("Receipt-to-expense mapping created.")


if __name__ == "__main__":
    main()
