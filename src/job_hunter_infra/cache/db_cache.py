"""Database-backed implementation of CacheClient using key/value table."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from job_hunter_infra.db.models import Base


class CacheEntry(Base):
    """Simple key/value cache table with optional expiry."""

    __tablename__ = "cache_entries"

    key: Mapped[str] = mapped_column(String(512), primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)


def _is_expired(expires_at: datetime) -> bool:
    """Check expiry, handling both naive and aware datetimes."""
    now = datetime.now(UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at < now


class DBCacheClient:
    """Cache implementation backed by the application's database."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with an async SQLAlchemy session."""
        self._session = session

    async def get(self, key: str) -> str | None:
        """Retrieve a value by key, or None if missing/expired."""
        entry = await self._session.get(CacheEntry, key)
        if entry is None:
            return None
        if entry.expires_at and _is_expired(entry.expires_at):
            await self._session.delete(entry)
            await self._session.commit()
            return None
        return entry.value

    async def set(self, key: str, value: str, ttl_seconds: int = 86400) -> None:
        """Store a value with TTL."""
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        entry = await self._session.get(CacheEntry, key)
        if entry is None:
            entry = CacheEntry(key=key, value=value, expires_at=expires_at)
            self._session.add(entry)
        else:
            entry.value = value
            entry.expires_at = expires_at
        await self._session.commit()

    async def delete(self, key: str) -> None:
        """Delete a key from the cache."""
        entry = await self._session.get(CacheEntry, key)
        if entry is None:
            return
        await self._session.delete(entry)
        await self._session.commit()

    async def exists(self, key: str) -> bool:
        """Check if a key exists and is not expired."""
        stmt = select(CacheEntry).where(CacheEntry.key == key)
        result = await self._session.execute(stmt)
        entry: CacheEntry | None = result.scalar_one_or_none()
        if entry is None:
            return False
        if entry.expires_at and _is_expired(entry.expires_at):
            await self._session.delete(entry)
            await self._session.commit()
            return False
        return True
