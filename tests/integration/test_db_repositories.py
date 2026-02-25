"""Integration tests for database repositories against real PostgreSQL."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from job_hunter_infra.db.models import (
    CompanyModel,
    NormalizedJobModel,
    ProfileModel,
    RawJobModel,
)
from tests.integration.conftest import skip_no_postgres

pytestmark = [pytest.mark.integration, skip_no_postgres]


class TestProfileRepository:
    """Profile table CRUD operations."""

    async def test_save_and_get_profile(self, db_session: AsyncSession) -> None:
        """Save a profile and retrieve it by content_hash."""
        profile_id = str(uuid4())
        content_hash = "a" * 64
        profile = ProfileModel(
            id=profile_id,
            content_hash=content_hash,
            email="jane@example.com",
            name="Jane Doe",
            years_of_experience=5.0,
            skills_json=[{"name": "Python"}],
            raw_text="Resume text here",
        )
        db_session.add(profile)
        await db_session.flush()

        result = await db_session.get(ProfileModel, profile_id)
        assert result is not None
        assert result.name == "Jane Doe"
        assert result.content_hash == content_hash

    async def test_unique_content_hash_constraint(self, db_session: AsyncSession) -> None:
        """Duplicate content_hash raises IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        content_hash = "b" * 64
        p1 = ProfileModel(
            id=str(uuid4()),
            content_hash=content_hash,
            email="a@example.com",
            name="User A",
            years_of_experience=3.0,
            skills_json=[],
            raw_text="text a",
        )
        p2 = ProfileModel(
            id=str(uuid4()),
            content_hash=content_hash,
            email="b@example.com",
            name="User B",
            years_of_experience=4.0,
            skills_json=[],
            raw_text="text b",
        )
        db_session.add(p1)
        await db_session.flush()

        db_session.add(p2)
        with pytest.raises(IntegrityError):
            await db_session.flush()


class TestCompanyRepository:
    """Company table CRUD operations."""

    async def test_save_and_list_companies(self, db_session: AsyncSession) -> None:
        """Save companies and list all."""
        from sqlalchemy import select

        c1 = CompanyModel(
            id=str(uuid4()),
            name="Acme Corp",
            domain="acme.com",
            career_url="https://acme.com/careers",
        )
        c2 = CompanyModel(
            id=str(uuid4()),
            name="DataFlow Inc",
            domain="dataflow.io",
            career_url="https://dataflow.io/careers",
        )
        db_session.add_all([c1, c2])
        await db_session.flush()

        result = await db_session.execute(select(CompanyModel))
        companies = result.scalars().all()
        assert len(companies) >= 2
        names = {c.name for c in companies}
        assert "Acme Corp" in names
        assert "DataFlow Inc" in names

    async def test_upsert_company(self, db_session: AsyncSession) -> None:
        """Update existing company by domain."""

        company_id = str(uuid4())
        c = CompanyModel(
            id=company_id,
            name="Old Name",
            domain="test.com",
            career_url="https://test.com/careers",
        )
        db_session.add(c)
        await db_session.flush()

        existing = await db_session.get(CompanyModel, company_id)
        assert existing is not None
        existing.name = "New Name"
        await db_session.flush()

        updated = await db_session.get(CompanyModel, company_id)
        assert updated is not None
        assert updated.name == "New Name"


class TestJobRepository:
    """Job table operations with foreign keys."""

    async def test_save_raw_and_normalized_jobs(self, db_session: AsyncSession) -> None:
        """Save raw job, then normalized job referencing it."""
        company_id = str(uuid4())
        company = CompanyModel(
            id=company_id,
            name="TestCo",
            domain="testco.com",
            career_url="https://testco.com/jobs",
        )
        db_session.add(company)
        await db_session.flush()

        raw_job_id = str(uuid4())
        raw = RawJobModel(
            id=raw_job_id,
            company_id=company_id,
            source_url="https://testco.com/jobs/1",
            scrape_strategy="api",
            raw_json={"title": "Engineer"},
        )
        db_session.add(raw)
        await db_session.flush()

        norm = NormalizedJobModel(
            id=str(uuid4()),
            raw_job_id=raw_job_id,
            company_id=company_id,
            company_name="TestCo",
            title="Software Engineer",
            jd_text="Build things.",
            apply_url="https://testco.com/apply/1",
            content_hash="c" * 64,
        )
        db_session.add(norm)
        await db_session.flush()

        result = await db_session.get(NormalizedJobModel, norm.id)
        assert result is not None
        assert result.title == "Software Engineer"
        assert result.company_id == company_id

    async def test_query_jobs_by_company(self, db_session: AsyncSession) -> None:
        """Query normalized jobs filtered by company_id."""
        from sqlalchemy import select

        company_id = str(uuid4())
        company = CompanyModel(
            id=company_id,
            name="FilterCo",
            domain="filterco.com",
            career_url="https://filterco.com/careers",
        )
        db_session.add(company)
        await db_session.flush()

        for i in range(3):
            db_session.add(
                NormalizedJobModel(
                    id=str(uuid4()),
                    company_id=company_id,
                    company_name="FilterCo",
                    title=f"Role {i}",
                    jd_text=f"Description {i}",
                    apply_url=f"https://filterco.com/apply/{i}",
                    content_hash=f"{'d' * 60}{i:04d}",
                )
            )
        await db_session.flush()

        result = await db_session.execute(
            select(NormalizedJobModel).where(NormalizedJobModel.company_id == company_id)
        )
        jobs = result.scalars().all()
        assert len(jobs) == 3

    async def test_foreign_key_constraint(self, db_session: AsyncSession) -> None:
        """Raw job with non-existent company_id raises IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        raw = RawJobModel(
            id=str(uuid4()),
            company_id=str(uuid4()),  # Non-existent company
            source_url="https://ghost.com/jobs/1",
            scrape_strategy="api",
        )
        db_session.add(raw)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_unique_content_hash_on_normalized_job(
        self, db_session: AsyncSession
    ) -> None:
        """Duplicate content_hash on normalized jobs raises IntegrityError."""
        from sqlalchemy.exc import IntegrityError

        company_id = str(uuid4())
        company = CompanyModel(
            id=company_id,
            name="DupCo",
            domain="dupco.com",
            career_url="https://dupco.com/careers",
        )
        db_session.add(company)
        await db_session.flush()

        content_hash = "e" * 64
        j1 = NormalizedJobModel(
            id=str(uuid4()),
            company_id=company_id,
            company_name="DupCo",
            title="Job A",
            jd_text="Desc A",
            apply_url="https://dupco.com/a",
            content_hash=content_hash,
        )
        j2 = NormalizedJobModel(
            id=str(uuid4()),
            company_id=company_id,
            company_name="DupCo",
            title="Job B",
            jd_text="Desc B",
            apply_url="https://dupco.com/b",
            content_hash=content_hash,
        )
        db_session.add(j1)
        await db_session.flush()

        db_session.add(j2)
        with pytest.raises(IntegrityError):
            await db_session.flush()
