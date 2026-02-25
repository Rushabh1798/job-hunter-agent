"""Run history repository for database operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from job_hunter_infra.db.models import RunHistoryModel


class RunRepository:
    """CRUD operations for run history."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with an async session."""
        self._session = session

    async def create(self, model: RunHistoryModel) -> RunHistoryModel:
        """Create a run history record."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def get_by_run_id(self, run_id: str) -> RunHistoryModel | None:
        """Retrieve a run by its run_id."""
        stmt = select(RunHistoryModel).where(RunHistoryModel.run_id == run_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_recent(self, limit: int = 10) -> list[RunHistoryModel]:
        """List recent runs ordered by creation time."""
        stmt = select(RunHistoryModel).order_by(RunHistoryModel.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
