"""Company repository for database operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from job_hunter_infra.db.models import CompanyModel


class CompanyRepository:
    """CRUD operations for companies."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize with an async session."""
        self._session = session

    async def get_by_id(self, company_id: str) -> CompanyModel | None:
        """Retrieve a company by ID."""
        return await self._session.get(CompanyModel, company_id)

    async def get_by_domain(self, domain: str) -> CompanyModel | None:
        """Retrieve a company by domain."""
        stmt = select(CompanyModel).where(CompanyModel.domain == domain)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, model: CompanyModel) -> CompanyModel:
        """Create a new company."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def upsert(self, model: CompanyModel) -> CompanyModel:
        """Create or update a company by domain."""
        existing = await self.get_by_domain(model.domain)
        if existing:
            existing.name = model.name
            existing.career_url = model.career_url
            existing.ats_type = model.ats_type
            await self._session.flush()
            return existing
        return await self.create(model)

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[CompanyModel]:
        """List companies with pagination."""
        stmt = select(CompanyModel).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
