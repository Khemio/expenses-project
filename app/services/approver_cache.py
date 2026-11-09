

import json
import os
from datetime import datetime, timezone

import redis
from dotenv import load_dotenv


load_dotenv()

redis_client = redis.Redis(
    host="localhost",
    port=6379,
    password=os.getenv("REDIS_PASSWORD"),
    decode_responses=True,
)


def cache_approver_chain(employee_id, approver_chain, source_id):
    key = f"approver_chain:{employee_id}"

    cache_data = {
        "approver_chain": approver_chain,
        "source_id": source_id,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }

    redis_client.set(
        key,
        json.dumps(cache_data),
        ex=300,
    )


def get_cached_approver_chain(employee_id):
    key = f"approver_chain:{employee_id}"
    cached = redis_client.get(key)

    if cached is None:
        return None

    return json.loads(cached)


def invalidate_approver_chain(employee_id):
    key = f"approver_chain:{employee_id}"
    redis_client.delete(key)
