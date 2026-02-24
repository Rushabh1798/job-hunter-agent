"""Page content cache for scraped HTML."""

from __future__ import annotations

import hashlib

from job_hunter_infra.cache.disk_cache import DiskCacheClient


class PageCache:
    """Cache for scraped page content, keyed by URL hash."""

    def __init__(self, cache: DiskCacheClient) -> None:
        """Initialize with a DiskCacheClient."""
        self._cache = cache

    def _key(self, url: str) -> str:
        """Generate a cache key from URL."""
        return f"page:{hashlib.sha256(url.encode()).hexdigest()}"

    async def get_page(self, url: str) -> str | None:
        """Retrieve cached page content by URL."""
        return await self._cache.get(self._key(url))

    async def set_page(self, url: str, content: str, ttl_hours: int = 24) -> None:
        """Cache page content with TTL."""
        await self._cache.set(self._key(url), content, ttl_seconds=ttl_hours * 3600)
