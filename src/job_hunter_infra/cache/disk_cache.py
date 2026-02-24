"""diskcache-backed implementation of CacheClient."""

from __future__ import annotations

import asyncio
from pathlib import Path

import diskcache


class DiskCacheClient:
    """Persistent cache backed by diskcache (SQLite under the hood)."""

    def __init__(self, cache_dir: Path) -> None:
        """Initialize with a cache directory."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = diskcache.Cache(str(cache_dir))

    async def get(self, key: str) -> str | None:
        """Retrieve a value by key."""
        result = await asyncio.to_thread(self._cache.get, key)
        if result is None:
            return None
        return str(result)

    async def set(self, key: str, value: str, ttl_seconds: int = 86400) -> None:
        """Store a value with TTL."""
        await asyncio.to_thread(self._cache.set, key, value, expire=ttl_seconds)

    async def delete(self, key: str) -> None:
        """Delete a key from the cache."""
        await asyncio.to_thread(self._cache.delete, key)

    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        result = await asyncio.to_thread(lambda: key in self._cache)
        return bool(result)

    def close(self) -> None:
        """Close the cache."""
        self._cache.close()
