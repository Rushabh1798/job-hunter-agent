"""Abstract cache interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CacheClient(Protocol):
    """Abstract cache interface — implementations can be swapped."""

    async def get(self, key: str) -> str | None:
        """Retrieve a value by key, or None if not found."""
        ...

    async def set(self, key: str, value: str, ttl_seconds: int = 86400) -> None:
        """Store a value with optional TTL."""
        ...

    async def delete(self, key: str) -> None:
        """Delete a key from the cache."""
        ...

    async def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        ...
