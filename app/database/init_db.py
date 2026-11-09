
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

connection = psycopg.connect(
    host="localhost",
    port=5432,
    dbname="expense_approval",
    user="expense_user",
    password=os.getenv("POSTGRES_PASSWORD"),
)

schema_path = Path(__file__).with_name("schema.sql")
schema = schema_path.read_text(encoding="utf-8")

with connection:
    with connection.cursor() as cursor:
        cursor.execute(schema)

connection.close()

print("Database schema initialized successfully!")
