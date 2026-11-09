
import os

POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5432
POSTGRES_DB = "expense_approval"
POSTGRES_USER = "expense_user"
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

MONGO_HOST = "localhost"
MONGO_PORT = 27017

REDIS_HOST = "localhost"
REDIS_PORT = 6379

NEO4J_URI = "bolt://localhost:7687"

QDRANT_URL = "http://localhost:6333"
