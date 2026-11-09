
from app.services.approver_cache import (
    cache_approver_chain,
    get_cached_approver_chain,
    invalidate_approver_chain,
    get_redis_client,
)


if __name__ == "__main__":
    employee_id = 1

    # Simulate the current approver chain
    original_chain = [2, 3]

    print("1. Caching the original approver chain...")
    cache_approver_chain(employee_id, original_chain)

    print(
        "Cached chain:",
        get_cached_approver_chain(employee_id),
    )

    # Simulate revoking a delegation in the source data.
    # Redis does not automatically know about this change.
    print("\n2. Simulating delegation revocation...")

    revoked_chain = [3]

    print(
        "Source chain after revocation:",
        revoked_chain,
    )

    # The cache still contains the old chain
    print(
        "Redis still returns:",
        get_cached_approver_chain(employee_id),
    )

    # Invalidate the cache
    print("\n3. Invalidating the Redis cache...")
    deleted = invalidate_approver_chain(employee_id)

    print("Cache keys deleted:", deleted)
    print(
        "Redis after invalidation:",
        get_cached_approver_chain(employee_id),
    )

    # Confirm TTL
    client = get_redis_client()
    client.set("test_ttl", "hello", ex=300)

    print(
        "\nTTL of test key:",
        client.ttl("test_ttl"),
        "seconds",
    )

    client.delete("test_ttl")
