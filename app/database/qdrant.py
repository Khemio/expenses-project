
from functools import lru_cache

from qdrant_client import QdrantClient

from app.config import get_settings


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    """Return the application's shared Qdrant client."""
    settings = get_settings()

    return QdrantClient(
        url=settings.qdrant_url,
        timeout=10,
    )


def close_qdrant_client() -> None:
    """Close the shared Qdrant client."""
    if get_qdrant_client.cache_info().currsize:
        get_qdrant_client().close()
        get_qdrant_client.cache_clear()
