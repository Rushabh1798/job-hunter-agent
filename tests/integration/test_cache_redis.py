"""Integration tests for Redis cache against real Redis."""

from __future__ import annotations

import asyncio

import pytest

from job_hunter_infra.cache.redis_cache import RedisCacheClient
from tests.integration.conftest import skip_no_redis

pytestmark = [pytest.mark.integration, skip_no_redis, pytest.mark.asyncio(loop_scope="session")]


class TestRedisCacheClient:
    """Redis cache operations against real Redis on localhost:6379/1."""

    async def test_set_get_roundtrip(self, redis_client: object) -> None:
        """Store a value and retrieve it."""
        from redis.asyncio import Redis

        assert isinstance(redis_client, Redis)
        cache = RedisCacheClient(redis_client)

        await cache.set("test:key", "hello world", ttl_seconds=60)
        result = await cache.get("test:key")
        assert result == "hello world"

    async def test_get_missing_key(self, redis_client: object) -> None:
        """Get on a missing key returns None."""
        from redis.asyncio import Redis

        assert isinstance(redis_client, Redis)
        cache = RedisCacheClient(redis_client)

        result = await cache.get("nonexistent:key")
        assert result is None

    async def test_ttl_expiry(self, redis_client: object) -> None:
        """Value expires after TTL."""
        from redis.asyncio import Redis

        assert isinstance(redis_client, Redis)
        cache = RedisCacheClient(redis_client)

        await cache.set("expiring:key", "temporary", ttl_seconds=1)
        assert await cache.get("expiring:key") == "temporary"

        await asyncio.sleep(2.5)
        assert await cache.get("expiring:key") is None

    async def test_delete_and_exists(self, redis_client: object) -> None:
        """Delete removes a key; exists checks presence."""
        from redis.asyncio import Redis

        assert isinstance(redis_client, Redis)
        cache = RedisCacheClient(redis_client)

        await cache.set("del:key", "value", ttl_seconds=60)
        assert await cache.exists("del:key") is True

        await cache.delete("del:key")
        assert await cache.exists("del:key") is False
        assert await cache.get("del:key") is None

    async def test_concurrent_operations(self, redis_client: object) -> None:
        """Multiple concurrent set/get operations succeed."""
        from redis.asyncio import Redis

        assert isinstance(redis_client, Redis)
        cache = RedisCacheClient(redis_client)

        async def _set_and_get(i: int) -> str | None:
            key = f"concurrent:{i}"
            await cache.set(key, f"value-{i}", ttl_seconds=60)
            return await cache.get(key)

        results = await asyncio.gather(*[_set_and_get(i) for i in range(10)])
        for i, result in enumerate(results):
            assert result == f"value-{i}"
