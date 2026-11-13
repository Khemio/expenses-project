
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


def required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise ValueError(
            f"Required environment variable {name} is not set"
        )

    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    mongo_uri: str
    redis_password: str
    neo4j_password: str

    redis_host: str = "localhost"
    redis_port: int = 6379

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"

    qdrant_url: str = "http://localhost:6333"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()

    return Settings(
        database_url=required_env("DATABASE_URL"),
        mongo_uri=required_env("MONGO_URI"),
        redis_password=required_env("REDIS_PASSWORD"),
        neo4j_password=required_env("NEO4J_PASSWORD"),
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        neo4j_uri=os.getenv(
            "NEO4J_URI", "bolt://localhost:7687"
        ),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        qdrant_url=os.getenv(
            "QDRANT_URL", "http://localhost:6333"
        ),
    )
