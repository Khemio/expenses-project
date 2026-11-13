
from functools import lru_cache

import redis

from app.config import get_settings


@lru_cache(maxsize=1)
def get_redis_client() -> redis.Redis:
    """Return the application's shared Redis client."""
    settings = get_settings()

    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def close_redis_client() -> None:
    """Close the shared Redis client and its connection pool."""
    if get_redis_client.cache_info().currsize:
        get_redis_client().close()
        get_redis_client.cache_clear()
