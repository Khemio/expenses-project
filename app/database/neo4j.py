
from functools import lru_cache

from neo4j import Driver, GraphDatabase

from app.config import get_settings


@lru_cache(maxsize=1)
def get_driver() -> Driver:
    """Return the application's shared Neo4j driver."""
    settings = get_settings()

    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(
            settings.neo4j_user,
            settings.neo4j_password,
        ),
    )


def close_driver() -> None:
    """Close the shared driver.

    Call during application shutdown, not after each query.
    """
    if get_driver.cache_info().currsize:
        get_driver().close()
        get_driver.cache_clear()
