"""Company career URL cache."""

from __future__ import annotations

from job_hunter_core.interfaces.cache import CacheClient


class CompanyURLCache:
    """Cache for company career page URLs."""

    def __init__(self, cache: CacheClient) -> None:
        """Initialize with a CacheClient implementation."""
        self._cache = cache

    def _key(self, company_name: str) -> str:
        """Generate a cache key from company name."""
        return f"company_url:{company_name.lower().strip()}"

    async def get_career_url(self, company_name: str) -> str | None:
        """Retrieve cached career URL for a company."""
        return await self._cache.get(self._key(company_name))

    async def set_career_url(self, company_name: str, url: str, ttl_days: int = 7) -> None:
        """Cache a company's career URL with TTL."""
        await self._cache.set(self._key(company_name), url, ttl_seconds=ttl_days * 86400)
