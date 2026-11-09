
import os

import psycopg
import pymongo
import redis
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from dotenv import load_dotenv

load_dotenv()

def test_postgres():
    with psycopg.connect(
        host="localhost",
        port=5432,
        dbname="expense_approval",
        user="expense_user",
        password=os.getenv("POSTGRES_PASSWORD"),
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            print("PostgreSQL:", cur.fetchone()[0])


def test_mongodb():
    client = pymongo.MongoClient(
        host="localhost",
        port=27017,
        username="expense_user",
        password=os.getenv("MONGO_PASSWORD"),
        authSource="admin",
        serverSelectionTimeoutMS=5000,
    )
    print("MongoDB:", client.admin.command("ping")["ok"])
    client.close()


def test_redis():
    client = redis.Redis(
        host="localhost",
        port=6379,
        password=os.getenv("REDIS_PASSWORD"),
        decode_responses=True,
    )
    client.set("connection_test", "success", ex=30)
    print("Redis:", client.get("connection_test"))
    client.close()


def test_neo4j():
    driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        auth=("neo4j", os.getenv("NEO4J_PASSWORD")),
    )

    with driver.session() as session:
        result = session.run("RETURN 1 AS value")
        print("Neo4j:", result.single()["value"])

    driver.close()


def test_qdrant():
    client = QdrantClient(url="http://localhost:6333")
    print("Qdrant:", client.get_collections())


if __name__ == "__main__":
    tests = [
        ("PostgreSQL", test_postgres),
        ("MongoDB", test_mongodb),
        ("Redis", test_redis),
        ("Neo4j", test_neo4j),
        ("Qdrant", test_qdrant),
    ]

    for name, test in tests:
        try:
            test()
            print(f" {name}: OK\n")
        except Exception as error:
            print(f" {name}: FAILED - {error}\n")
