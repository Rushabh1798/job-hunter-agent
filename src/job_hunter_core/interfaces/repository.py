"""Abstract repository interface."""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable
from uuid import UUID

T = TypeVar("T")


@runtime_checkable
class BaseRepository(Protocol[T]):
    """Abstract repository interface for database operations."""

    async def get_by_id(self, entity_id: UUID) -> T | None:
        """Retrieve an entity by its ID."""
        ...

    async def create(self, entity: T) -> T:
        """Create a new entity."""
        ...

    async def upsert(self, entity: T) -> T:
        """Create or update an entity."""
        ...

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        """List entities with pagination."""
        ...
