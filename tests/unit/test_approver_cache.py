
import json

import pytest

from app.services import approver_cache


class FakeRedis:
    """Minimal in-memory Redis implementation for testing."""

    def __init__(self):
        self.data = {}
        self.expirations = {}

    def set(self, key, value, ex=None):
        self.data[key] = value
        self.expirations[key] = ex

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        existed = key in self.data
        self.data.pop(key, None)
        self.expirations.pop(key, None)
        return int(existed)


@pytest.fixture
def fake_redis(monkeypatch):
    client = FakeRedis()

    monkeypatch.setattr(
        approver_cache,
        "get_redis_client",
        lambda: client,
    )

    return client


def test_cache_approver_chain(fake_redis):
    approver_cache.cache_approver_chain(
        employee_id=1,
        approver_chain=[2, 3],
        source_id="test_source",
    )

    cached = approver_cache.get_cached_approver_chain(1)

    assert cached["approver_chain"] == [2, 3]
    assert cached["source_id"] == "test_source"
    assert "refreshed_at" in cached


def test_cache_has_ttl(fake_redis):
    approver_cache.cache_approver_chain(
        employee_id=1,
        approver_chain=[2, 3],
        source_id="test_source",
    )

    assert fake_redis.expirations["approver_chain:1"] == 300


def test_invalidate_approver_chain(fake_redis):
    approver_cache.cache_approver_chain(
        employee_id=1,
        approver_chain=[2, 3],
        source_id="test_source",
    )

    deleted = approver_cache.invalidate_approver_chain(1)

    assert deleted == 1
    assert approver_cache.get_cached_approver_chain(1) is None


def test_missing_cache_entry(fake_redis):
    assert approver_cache.get_cached_approver_chain(999) is None


def test_cache_overwrite(fake_redis):
    approver_cache.cache_approver_chain(
        employee_id=1,
        approver_chain=[2, 3],
        source_id="original",
    )

    approver_cache.cache_approver_chain(
        employee_id=1,
        approver_chain=[3],
        source_id="updated",
    )

    cached = approver_cache.get_cached_approver_chain(1)

    assert cached["approver_chain"] == [3]
    assert cached["source_id"] == "updated"
