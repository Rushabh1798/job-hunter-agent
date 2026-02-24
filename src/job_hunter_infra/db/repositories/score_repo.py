"""Score repository for database operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from job_hunter_infra.db.models import ScoredJobModel


class ScoreRepository:
    """CRUD operations for scored jobs."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with an async session."""
        self._session = session

    async def create(self, model: ScoredJobModel) -> ScoredJobModel:
        """Create a scored job record."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def list_by_run(
        self, run_id: str, limit: int = 100
    ) -> list[ScoredJobModel]:
        """List scored jobs for a given run, ordered by score descending."""
        stmt = (
            select(ScoredJobModel)
            .where(ScoredJobModel.run_id == run_id)
            .order_by(ScoredJobModel.score.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
