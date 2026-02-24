"""Tests for database repositories using SQLite."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from job_hunter_infra.db.models import Base, CompanyModel, ProfileModel
from job_hunter_infra.db.repositories.company_repo import CompanyRepository
from job_hunter_infra.db.repositories.profile_repo import ProfileRepository
from job_hunter_infra.db.session import create_session_factory


@pytest.fixture
async def session() -> AsyncSession:  # type: ignore[misc]
    """Create an in-memory SQLite session for testing."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as sess:
        yield sess  # type: ignore[misc]
    await engine.dispose()


@pytest.mark.unit
class TestProfileRepository:
    """Test ProfileRepository CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_and_get(self, session: AsyncSession) -> None:
        """Create a profile and retrieve it by ID."""
        repo = ProfileRepository(session)
        model = ProfileModel(
            content_hash="hash123",
            email="test@example.com",
            name="Test User",
            years_of_experience=5.0,
            skills_json=[{"name": "Python"}],
            raw_text="Resume text",
        )
        created = await repo.create(model)
        assert created.id is not None

        fetched = await repo.get_by_id(created.id)
        assert fetched is not None
        assert fetched.email == "test@example.com"

    @pytest.mark.asyncio
    async def test_get_by_content_hash(self, session: AsyncSession) -> None:
        """Retrieve a profile by content hash."""
        repo = ProfileRepository(session)
        model = ProfileModel(
            content_hash="unique_hash",
            email="test@example.com",
            name="Test",
            years_of_experience=3.0,
            skills_json=[],
            raw_text="text",
        )
        await repo.create(model)

        found = await repo.get_by_content_hash("unique_hash")
        assert found is not None
        assert found.name == "Test"

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, session: AsyncSession) -> None:
        """Upsert updates an existing profile with the same content_hash."""
        repo = ProfileRepository(session)
        model1 = ProfileModel(
            content_hash="same_hash",
            email="v1@example.com",
            name="V1",
            years_of_experience=1.0,
            skills_json=[],
            raw_text="v1",
        )
        await repo.create(model1)

        model2 = ProfileModel(
            content_hash="same_hash",
            email="v2@example.com",
            name="V2",
            years_of_experience=2.0,
            skills_json=[],
            raw_text="v2",
        )
        result = await repo.upsert(model2)
        assert result.email == "v2@example.com"


@pytest.mark.unit
class TestCompanyRepository:
    """Test CompanyRepository CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_and_get_by_domain(self, session: AsyncSession) -> None:
        """Create a company and find it by domain."""
        repo = CompanyRepository(session)
        model = CompanyModel(
            name="Stripe",
            domain="stripe.com",
            career_url="https://stripe.com/careers",
        )
        await repo.create(model)

        found = await repo.get_by_domain("stripe.com")
        assert found is not None
        assert found.name == "Stripe"

    @pytest.mark.asyncio
    async def test_list_all(self, session: AsyncSession) -> None:
        """List companies with pagination."""
        repo = CompanyRepository(session)
        for i in range(3):
            await repo.create(CompanyModel(
                name=f"Company {i}",
                domain=f"company{i}.com",
                career_url=f"https://company{i}.com/careers",
            ))
        results = await repo.list_all(limit=2)
        assert len(results) == 2
