"""Tests for all cache backends and cache wrappers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from job_hunter_infra.cache.company_cache import CompanyURLCache
from job_hunter_infra.cache.db_cache import CacheEntry, DBCacheClient
from job_hunter_infra.cache.page_cache import PageCache
from job_hunter_infra.cache.redis_cache import RedisCacheClient
from job_hunter_infra.db.models import Base

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create an in-memory SQLite session for DB cache tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session  # type: ignore[misc]
    await engine.dispose()


def _make_mock_redis() -> MagicMock:
    """Create a mock redis.asyncio.Redis client."""
    mock = MagicMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock()
    mock.delete = AsyncMock()
    mock.exists = AsyncMock(return_value=0)
    return mock


# ---------------------------------------------------------------------------
# TestDBCacheClient
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDBCacheClient:
    """Tests for database-backed cache."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, db_session: AsyncSession) -> None:
        """Store a value and retrieve it."""
        cache = DBCacheClient(db_session)
        await cache.set("key1", "value1", ttl_seconds=60)
        assert await cache.get("key1") == "value1"

    @pytest.mark.asyncio
    async def test_get_missing_key(self, db_session: AsyncSession) -> None:
        """Missing key returns None."""
        cache = DBCacheClient(db_session)
        assert await cache.get("missing") is None

    @pytest.mark.asyncio
    async def test_exists_and_delete(self, db_session: AsyncSession) -> None:
        """Exists returns correct state; delete removes."""
        cache = DBCacheClient(db_session)
        assert await cache.exists("key1") is False
        await cache.set("key1", "value1", ttl_seconds=60)
        assert await cache.exists("key1") is True
        await cache.delete("key1")
        assert await cache.exists("key1") is False

    @pytest.mark.asyncio
    async def test_expired_entry_returns_none(self, db_session: AsyncSession) -> None:
        """Expired entries are treated as missing and cleaned up."""
        expired = CacheEntry(
            key="expired",
            value="stale",
            expires_at=datetime.now(UTC) - timedelta(seconds=10),
        )
        db_session.add(expired)
        await db_session.commit()

        cache = DBCacheClient(db_session)
        assert await cache.get("expired") is None
        assert await cache.exists("expired") is False

    @pytest.mark.asyncio
    async def test_overwrite_existing_key(self, db_session: AsyncSession) -> None:
        """Setting an existing key overwrites the value."""
        cache = DBCacheClient(db_session)
        await cache.set("k", "v1", ttl_seconds=60)
        await cache.set("k", "v2", ttl_seconds=60)
        assert await cache.get("k") == "v2"

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key(self, db_session: AsyncSession) -> None:
        """Deleting a missing key is a no-op."""
        cache = DBCacheClient(db_session)
        await cache.delete("nope")  # should not raise


# ---------------------------------------------------------------------------
# TestRedisCacheClient
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRedisCacheClient:
    """Tests for Redis-backed cache with mocked redis client."""

    @pytest.mark.asyncio
    async def test_get_returns_decoded_bytes(self) -> None:
        """Redis bytes are decoded to str."""
        mock_redis = _make_mock_redis()
        mock_redis.get.return_value = b"hello"
        cache = RedisCacheClient(mock_redis)
        result = await cache.get("k")
        assert result == "hello"
        mock_redis.get.assert_awaited_once_with("k")

    @pytest.mark.asyncio
    async def test_get_returns_none_on_miss(self) -> None:
        """Cache miss returns None."""
        mock_redis = _make_mock_redis()
        cache = RedisCacheClient(mock_redis)
        assert await cache.get("missing") is None

    @pytest.mark.asyncio
    async def test_set_calls_redis_with_ttl(self) -> None:
        """Set passes name, value, and ex to Redis."""
        mock_redis = _make_mock_redis()
        cache = RedisCacheClient(mock_redis)
        await cache.set("k", "v", ttl_seconds=120)
        mock_redis.set.assert_awaited_once_with(name="k", value="v", ex=120)

    @pytest.mark.asyncio
    async def test_delete_calls_redis(self) -> None:
        """Delete forwards to Redis."""
        mock_redis = _make_mock_redis()
        cache = RedisCacheClient(mock_redis)
        await cache.delete("k")
        mock_redis.delete.assert_awaited_once_with("k")

    @pytest.mark.asyncio
    async def test_exists_true(self) -> None:
        """Exists returns True when Redis reports key present."""
        mock_redis = _make_mock_redis()
        mock_redis.exists.return_value = 1
        cache = RedisCacheClient(mock_redis)
        assert await cache.exists("k") is True

    @pytest.mark.asyncio
    async def test_exists_false(self) -> None:
        """Exists returns False when Redis reports key absent."""
        mock_redis = _make_mock_redis()
        cache = RedisCacheClient(mock_redis)
        assert await cache.exists("k") is False

    @pytest.mark.asyncio
    async def test_get_returns_str_value(self) -> None:
        """Non-bytes value is coerced to str."""
        mock_redis = _make_mock_redis()
        mock_redis.get.return_value = "already-str"
        cache = RedisCacheClient(mock_redis)
        assert await cache.get("k") == "already-str"


# ---------------------------------------------------------------------------
# TestPageCache
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPageCache:
    """Tests for PageCache wrapper."""

    @pytest.mark.asyncio
    async def test_set_and_get_page(self) -> None:
        """Page content is cached by URL hash."""
        inner = AsyncMock()
        inner.get = AsyncMock(return_value="<html>content</html>")
        cache = PageCache(inner)

        await cache.set_page("https://example.com/jobs", "<html>content</html>", ttl_hours=1)
        result = await cache.get_page("https://example.com/jobs")

        assert result == "<html>content</html>"
        inner.set.assert_awaited_once()
        # TTL should be 1 hour = 3600 seconds
        call_kwargs = inner.set.call_args
        assert call_kwargs[1]["ttl_seconds"] == 3600

    @pytest.mark.asyncio
    async def test_get_page_miss(self) -> None:
        """Missing page returns None."""
        inner = AsyncMock()
        inner.get = AsyncMock(return_value=None)
        cache = PageCache(inner)
        assert await cache.get_page("https://missing.com") is None

    @pytest.mark.asyncio
    async def test_key_is_deterministic(self) -> None:
        """Same URL always produces the same cache key."""
        cache = PageCache(AsyncMock())
        key1 = cache._key("https://example.com")
        key2 = cache._key("https://example.com")
        assert key1 == key2
        assert key1.startswith("page:")


# ---------------------------------------------------------------------------
# TestCompanyURLCache
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompanyURLCache:
    """Tests for CompanyURLCache wrapper."""

    @pytest.mark.asyncio
    async def test_set_and_get_career_url(self) -> None:
        """Career URL is cached by normalized company name."""
        inner = AsyncMock()
        inner.get = AsyncMock(return_value="https://stripe.com/jobs")
        cache = CompanyURLCache(inner)

        await cache.set_career_url("Stripe", "https://stripe.com/jobs", ttl_days=7)
        result = await cache.get_career_url("Stripe")

        assert result == "https://stripe.com/jobs"
        # TTL should be 7 days = 604800 seconds
        call_kwargs = inner.set.call_args
        assert call_kwargs[1]["ttl_seconds"] == 604800

    @pytest.mark.asyncio
    async def test_key_is_case_insensitive(self) -> None:
        """Company name is lowercased for key generation."""
        cache = CompanyURLCache(AsyncMock())
        assert cache._key("Stripe") == cache._key("stripe")
        assert cache._key("  Stripe  ") == cache._key("stripe")

    @pytest.mark.asyncio
    async def test_get_career_url_miss(self) -> None:
        """Missing company returns None."""
        inner = AsyncMock()
        inner.get = AsyncMock(return_value=None)
        cache = CompanyURLCache(inner)
        assert await cache.get_career_url("Unknown Corp") is None
