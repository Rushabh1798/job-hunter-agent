"""Redis-backed implementation of CacheClient."""

from __future__ import annotations

from redis.asyncio import Redis


class RedisCacheClient:
    """Persistent cache backed by Redis."""

    def __init__(self, redis: Redis) -> None:  # type: ignore[type-arg]
        """Initialize with a redis-py asyncio client."""
        self._redis = redis

    async def get(self, key: str) -> str | None:
        """Retrieve a value by key."""
        value = await self._redis.get(key)
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    async def set(self, key: str, value: str, ttl_seconds: int = 86400) -> None:
        """Store a value with TTL."""
        await self._redis.set(name=key, value=value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        """Delete a key from the cache."""
        await self._redis.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        count = await self._redis.exists(key)
        return bool(count)
