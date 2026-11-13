
import json
from datetime import datetime, timezone

from app.database.redis import get_redis_client


CACHE_TTL_SECONDS = 300


def cache_approver_chain(
    employee_id: int,
    approver_chain: list[int],
    source_id: str,
) -> None:
    key = f"approver_chain:{employee_id}"

    cache_data = {
        "approver_chain": approver_chain,
        "source_id": source_id,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }

    get_redis_client().set(
        key,
        json.dumps(cache_data),
        ex=CACHE_TTL_SECONDS,
    )


def get_cached_approver_chain(employee_id: int):
    key = f"approver_chain:{employee_id}"
    cached = get_redis_client().get(key)

    if cached is None:
        return None

    return json.loads(cached)


def invalidate_approver_chain(employee_id: int) -> int:
    key = f"approver_chain:{employee_id}"
    return get_redis_client().delete(key)
