"""Tests for DiskCacheClient."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from job_hunter_infra.cache.disk_cache import DiskCacheClient


@pytest.fixture
def cache_client() -> DiskCacheClient:
    """Create a temporary DiskCacheClient."""
    with tempfile.TemporaryDirectory() as tmpdir:
        client = DiskCacheClient(Path(tmpdir) / "test_cache")
        yield client  # type: ignore[misc]
        client.close()


@pytest.mark.unit
class TestDiskCacheClient:
    """Test DiskCacheClient operations."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache_client: DiskCacheClient) -> None:
        """Set a value and retrieve it."""
        await cache_client.set("key1", "value1")
        result = await cache_client.get("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_get_missing_key(self, cache_client: DiskCacheClient) -> None:
        """Get on missing key returns None."""
        result = await cache_client.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_exists(self, cache_client: DiskCacheClient) -> None:
        """Exists returns correct boolean."""
        assert await cache_client.exists("key1") is False
        await cache_client.set("key1", "value1")
        assert await cache_client.exists("key1") is True

    @pytest.mark.asyncio
    async def test_delete(self, cache_client: DiskCacheClient) -> None:
        """Delete removes a key."""
        await cache_client.set("key1", "value1")
        await cache_client.delete("key1")
        assert await cache_client.get("key1") is None
