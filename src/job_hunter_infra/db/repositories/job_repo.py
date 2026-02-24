"""Job repository for database operations including vector queries."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from job_hunter_infra.db.models import NormalizedJobModel, RawJobModel


class JobRepository:
    """CRUD operations for raw and normalized jobs."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with an async session."""
        self._session = session

    async def create_raw(self, model: RawJobModel) -> RawJobModel:
        """Create a raw job record."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def create_normalized(self, model: NormalizedJobModel) -> NormalizedJobModel:
        """Create a normalized job record."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def get_normalized_by_hash(self, content_hash: str) -> NormalizedJobModel | None:
        """Check if a normalized job with this content hash already exists."""
        stmt = select(NormalizedJobModel).where(
            NormalizedJobModel.content_hash == content_hash
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_normalized(self, model: NormalizedJobModel) -> NormalizedJobModel:
        """Create or skip a normalized job by content_hash."""
        existing = await self.get_normalized_by_hash(model.content_hash)
        if existing:
            return existing
        return await self.create_normalized(model)

    async def list_normalized(
        self, limit: int = 100, offset: int = 0
    ) -> list[NormalizedJobModel]:
        """List normalized jobs with pagination."""
        stmt = select(NormalizedJobModel).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_with_embeddings(self) -> list[tuple[NormalizedJobModel, list[float]]]:
        """Get all normalized jobs that have embeddings (for SQLite brute-force search)."""
        stmt = select(NormalizedJobModel).where(
            NormalizedJobModel.embedding_json.isnot(None)
        )
        result = await self._session.execute(stmt)
        jobs = result.scalars().all()
        pairs: list[tuple[NormalizedJobModel, list[float]]] = []
        for job in jobs:
            if job.embedding_json:
                embedding = json.loads(job.embedding_json)
                pairs.append((job, embedding))
        return pairs
