"""Profile repository for database operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from job_hunter_infra.db.models import ProfileModel


class ProfileRepository:
    """CRUD operations for candidate profiles."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with an async session."""
        self._session = session

    async def get_by_id(self, profile_id: str) -> ProfileModel | None:
        """Retrieve a profile by ID."""
        return await self._session.get(ProfileModel, profile_id)

    async def get_by_content_hash(self, content_hash: str) -> ProfileModel | None:
        """Retrieve a profile by content hash."""
        stmt = select(ProfileModel).where(ProfileModel.content_hash == content_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, model: ProfileModel) -> ProfileModel:
        """Create a new profile."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def upsert(self, model: ProfileModel) -> ProfileModel:
        """Create or update a profile by content_hash."""
        existing = await self.get_by_content_hash(model.content_hash)
        if existing:
            existing.email = model.email
            existing.name = model.name
            existing.skills_json = model.skills_json
            existing.raw_text = model.raw_text
            await self._session.flush()
            return existing
        return await self.create(model)
