"""Tests for job, run, and score repositories using SQLite."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from job_hunter_infra.db.models import (
    Base,
    CompanyModel,
    NormalizedJobModel,
    RawJobModel,
    RunHistoryModel,
    ScoredJobModel,
)
from job_hunter_infra.db.repositories.job_repo import JobRepository
from job_hunter_infra.db.repositories.run_repo import RunRepository
from job_hunter_infra.db.repositories.score_repo import ScoreRepository
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
class TestJobRepository:
    """Test JobRepository CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_raw_job(self, session: AsyncSession) -> None:
        """Create a raw job record."""
        company = CompanyModel(
            name="Acme", domain="acme.com", career_url="https://acme.com/careers"
        )
        session.add(company)
        await session.flush()

        repo = JobRepository(session)
        raw = RawJobModel(
            company_id=company.id,
            source_url="https://acme.com/jobs/1",
            scrape_strategy="crawl4ai",
        )
        created = await repo.create_raw(raw)
        assert created.id is not None

    @pytest.mark.asyncio
    async def test_create_and_get_normalized(self, session: AsyncSession) -> None:
        """Create a normalized job and retrieve by hash."""
        company = CompanyModel(
            name="Acme", domain="acme.com", career_url="https://acme.com/careers"
        )
        session.add(company)
        await session.flush()

        repo = JobRepository(session)
        norm = NormalizedJobModel(
            company_id=company.id,
            company_name="Acme",
            title="SWE",
            jd_text="Build things",
            apply_url="https://acme.com/apply",
            content_hash="abc123",
        )
        created = await repo.create_normalized(norm)
        assert created.id is not None

        found = await repo.get_normalized_by_hash("abc123")
        assert found is not None
        assert found.title == "SWE"

    @pytest.mark.asyncio
    async def test_get_normalized_by_hash_not_found(self, session: AsyncSession) -> None:
        """Returns None when hash doesn't exist."""
        repo = JobRepository(session)
        found = await repo.get_normalized_by_hash("nonexistent")
        assert found is None

    @pytest.mark.asyncio
    async def test_upsert_normalized_creates_new(self, session: AsyncSession) -> None:
        """Upsert creates when no existing job with hash."""
        company = CompanyModel(
            name="Acme", domain="acme.com", career_url="https://acme.com/careers"
        )
        session.add(company)
        await session.flush()

        repo = JobRepository(session)
        norm = NormalizedJobModel(
            company_id=company.id,
            company_name="Acme",
            title="SWE",
            jd_text="Build things",
            apply_url="https://acme.com/apply",
            content_hash="new_hash",
        )
        result = await repo.upsert_normalized(norm)
        assert result.title == "SWE"

    @pytest.mark.asyncio
    async def test_upsert_normalized_returns_existing(self, session: AsyncSession) -> None:
        """Upsert returns existing job when hash matches."""
        company = CompanyModel(
            name="Acme", domain="acme.com", career_url="https://acme.com/careers"
        )
        session.add(company)
        await session.flush()

        repo = JobRepository(session)
        norm1 = NormalizedJobModel(
            company_id=company.id,
            company_name="Acme",
            title="SWE v1",
            jd_text="Build things",
            apply_url="https://acme.com/apply",
            content_hash="dup_hash",
        )
        await repo.create_normalized(norm1)

        norm2 = NormalizedJobModel(
            company_id=company.id,
            company_name="Acme",
            title="SWE v2",
            jd_text="Different",
            apply_url="https://acme.com/apply",
            content_hash="dup_hash",
        )
        result = await repo.upsert_normalized(norm2)
        assert result.title == "SWE v1"

    @pytest.mark.asyncio
    async def test_list_normalized(self, session: AsyncSession) -> None:
        """List normalized jobs with pagination."""
        company = CompanyModel(
            name="Acme", domain="acme.com", career_url="https://acme.com/careers"
        )
        session.add(company)
        await session.flush()

        repo = JobRepository(session)
        for i in range(3):
            await repo.create_normalized(
                NormalizedJobModel(
                    company_id=company.id,
                    company_name="Acme",
                    title=f"Job {i}",
                    jd_text="Description",
                    apply_url="https://acme.com/apply",
                    content_hash=f"hash_{i}",
                )
            )
        results = await repo.list_normalized(limit=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_all_with_embeddings(self, session: AsyncSession) -> None:
        """Get jobs that have embeddings."""
        company = CompanyModel(
            name="Acme", domain="acme.com", career_url="https://acme.com/careers"
        )
        session.add(company)
        await session.flush()

        repo = JobRepository(session)
        await repo.create_normalized(
            NormalizedJobModel(
                company_id=company.id,
                company_name="Acme",
                title="With Embedding",
                jd_text="Description",
                apply_url="https://acme.com/apply",
                content_hash="emb_hash",
                embedding_json=json.dumps([0.1, 0.2, 0.3]),
            )
        )
        await repo.create_normalized(
            NormalizedJobModel(
                company_id=company.id,
                company_name="Acme",
                title="No Embedding",
                jd_text="Description",
                apply_url="https://acme.com/apply",
                content_hash="no_emb_hash",
            )
        )

        pairs = await repo.get_all_with_embeddings()
        assert len(pairs) == 1
        job, embedding = pairs[0]
        assert job.title == "With Embedding"
        assert embedding == [0.1, 0.2, 0.3]


@pytest.mark.unit
class TestRunRepository:
    """Test RunRepository CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_and_get_by_run_id(self, session: AsyncSession) -> None:
        """Create a run and retrieve by run_id."""
        repo = RunRepository(session)
        model = RunHistoryModel(
            run_id="run-001",
            status="completed",
            companies_attempted=5,
            jobs_scraped=20,
        )
        created = await repo.create(model)
        assert created.id is not None

        found = await repo.get_by_run_id("run-001")
        assert found is not None
        assert found.status == "completed"
        assert found.companies_attempted == 5

    @pytest.mark.asyncio
    async def test_get_by_run_id_not_found(self, session: AsyncSession) -> None:
        """Returns None for non-existent run_id."""
        repo = RunRepository(session)
        found = await repo.get_by_run_id("nonexistent")
        assert found is None

    @pytest.mark.asyncio
    async def test_list_recent(self, session: AsyncSession) -> None:
        """List recent runs ordered by creation time."""
        repo = RunRepository(session)
        for i in range(5):
            await repo.create(RunHistoryModel(run_id=f"run-{i:03d}", status="completed"))
        results = await repo.list_recent(limit=3)
        assert len(results) == 3


@pytest.mark.unit
class TestScoreRepository:
    """Test ScoreRepository CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_scored_job(self, session: AsyncSession) -> None:
        """Create a scored job record."""
        company = CompanyModel(
            name="Acme", domain="acme.com", career_url="https://acme.com/careers"
        )
        session.add(company)
        await session.flush()

        norm = NormalizedJobModel(
            company_id=company.id,
            company_name="Acme",
            title="SWE",
            jd_text="Build things",
            apply_url="https://acme.com/apply",
            content_hash="score_hash",
        )
        session.add(norm)
        await session.flush()

        repo = ScoreRepository(session)
        scored = ScoredJobModel(
            normalized_job_id=norm.id,
            run_id="run-001",
            score=85,
            fit_summary="Good fit",
        )
        created = await repo.create(scored)
        assert created.id is not None

    @pytest.mark.asyncio
    async def test_list_by_run_ordered_by_score(self, session: AsyncSession) -> None:
        """List scored jobs for a run, ordered by score descending."""
        company = CompanyModel(
            name="Acme", domain="acme.com", career_url="https://acme.com/careers"
        )
        session.add(company)
        await session.flush()

        norms = []
        for i in range(3):
            n = NormalizedJobModel(
                company_id=company.id,
                company_name="Acme",
                title=f"Job {i}",
                jd_text="Desc",
                apply_url="https://acme.com/apply",
                content_hash=f"score_hash_{i}",
            )
            session.add(n)
            await session.flush()
            norms.append(n)

        repo = ScoreRepository(session)
        for i, n in enumerate(norms):
            await repo.create(
                ScoredJobModel(
                    normalized_job_id=n.id,
                    run_id="run-001",
                    score=(i + 1) * 20,
                )
            )

        results = await repo.list_by_run("run-001")
        assert len(results) == 3
        assert results[0].score >= results[1].score >= results[2].score

    @pytest.mark.asyncio
    async def test_list_by_run_empty(self, session: AsyncSession) -> None:
        """Returns empty list when no scored jobs for run."""
        repo = ScoreRepository(session)
        results = await repo.list_by_run("nonexistent-run")
        assert results == []
