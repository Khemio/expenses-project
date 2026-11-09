
import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

with psycopg.connect(os.getenv("DATABASE_URL")) as conn:
    with conn.cursor() as cur:

        print("\n--- Extension installation ---")
        cur.execute("""
            SELECT extname, extversion, extnamespace::regnamespace
            FROM pg_extension
            WHERE extname = 'vector';
        """)
        print(cur.fetchall())

        print("\n--- Vector type ---")
        cur.execute("""
            SELECT typname, typnamespace::regnamespace
            FROM pg_type
            WHERE typname = 'vector';
        """)
        print(cur.fetchall())

        print("\n--- HNSW indexes ---")
        cur.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'vector_documents'
              AND indexdef ILIKE '%hnsw%';
        """)
        print(cur.fetchall())

        print("\n--- Load vector extension into session ---")
        cur.execute("LOAD 'vector';")
        print("Vector library loaded.")

        print("\n--- HNSW settings after LOAD ---")
        cur.execute("""
            SELECT name, setting
            FROM pg_settings
            WHERE name LIKE 'hnsw.%'
            ORDER BY name;
        """)
        print(cur.fetchall())
