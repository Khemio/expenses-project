
from uuid import uuid4

import pytest

from app.database.redis import get_redis_client
from app.services.approver_cache import (
    CACHE_TTL_SECONDS,
    cache_approver_chain,
    get_cached_approver_chain,
    invalidate_approver_chain,
)


@pytest.fixture
def cache_employee_id():
    # Keep each test's Redis key independent.
    employee_id = uuid4().int

    client = get_redis_client()
    key = f"approver_chain:{employee_id}"

    client.delete(key)

    try:
        yield employee_id
    finally:
        client.delete(key)


@pytest.mark.integration
def test_real_redis_cache_round_trip(cache_employee_id):
    cache_approver_chain(
        employee_id=cache_employee_id,
        approver_chain=[10, 20, 30],
        source_id="integration-test",
    )

    cached = get_cached_approver_chain(
        cache_employee_id
    )

    assert cached["approver_chain"] == [10, 20, 30]
    assert cached["source_id"] == "integration-test"
    assert "refreshed_at" in cached


@pytest.mark.integration
def test_real_redis_cache_ttl(cache_employee_id):
    cache_approver_chain(
        employee_id=cache_employee_id,
        approver_chain=[10, 20],
        source_id="integration-test",
    )

    key = f"approver_chain:{cache_employee_id}"

    ttl = get_redis_client().ttl(key)

    assert 0 < ttl <= CACHE_TTL_SECONDS


@pytest.mark.integration
def test_real_redis_cache_invalidation(
    cache_employee_id,
):
    cache_approver_chain(
        employee_id=cache_employee_id,
        approver_chain=[10, 20],
        source_id="integration-test",
    )

    assert invalidate_approver_chain(
        cache_employee_id
    ) == 1

    assert get_cached_approver_chain(
        cache_employee_id
    ) is None
