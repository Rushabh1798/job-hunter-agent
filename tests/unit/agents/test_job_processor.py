"""Tests for job processor agent."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from job_hunter_agents.agents.job_processor import (
    ExtractedJob,
    JobProcessorAgent,
    _normalize_remote_type,
)
from job_hunter_core.models.job import RawJob
from job_hunter_core.models.run import RunConfig
from job_hunter_core.state import PipelineState
from tests.mocks.mock_settings import make_settings


def _make_raw_job_json() -> RawJob:
    """Create raw job with JSON data (ATS API)."""
    return RawJob(
        company_id=uuid4(),
        company_name="Stripe",
        raw_json={
            "title": "Software Engineer",
            "content": "We are looking for a great SWE...",
            "location": {"name": "San Francisco, CA"},
            "absolute_url": "https://boards.greenhouse.io/stripe/jobs/123",
        },
        source_url="https://boards.greenhouse.io/stripe/jobs",
        scrape_strategy="api",
        source_confidence=0.95,
    )


def _make_raw_job_html() -> RawJob:
    """Create raw job with HTML content."""
    return RawJob(
        company_id=uuid4(),
        company_name="Acme",
        raw_html="<div>Senior Python Developer at Acme Corp...</div>" * 5,
        source_url="https://acme.com/careers/senior-python",
        scrape_strategy="crawl4ai",
        source_confidence=0.7,
    )


@pytest.mark.unit
class TestJobProcessorAgent:
    """Test JobProcessorAgent."""

    @pytest.mark.asyncio
    async def test_process_json_job(self) -> None:
        """JSON jobs are processed without LLM call."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="test",
            )
        )
        state.raw_jobs = [_make_raw_job_json()]

        agent = JobProcessorAgent(settings)
        result = await agent.run(state)

        assert len(result.normalized_jobs) == 1
        assert result.normalized_jobs[0].title == "Software Engineer"
        assert result.normalized_jobs[0].company_name == "Stripe"

    @pytest.mark.asyncio
    async def test_deduplication_by_hash(self) -> None:
        """Duplicate jobs are deduplicated by content hash."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="test",
            )
        )
        job = _make_raw_job_json()
        state.raw_jobs = [job, job]

        agent = JobProcessorAgent(settings)
        result = await agent.run(state)

        assert len(result.normalized_jobs) == 1

    @pytest.mark.asyncio
    async def test_process_error_recorded(self) -> None:
        """Processing error is recorded, not raised."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="test",
            )
        )
        bad_job = RawJob(
            company_id=uuid4(),
            company_name="Bad",
            raw_json={"no_title": True},
            source_url="https://bad.com",
            scrape_strategy="api",
            source_confidence=0.5,
        )
        state.raw_jobs = [bad_job]

        agent = JobProcessorAgent(settings)
        result = await agent.run(state)

        assert len(result.normalized_jobs) == 0

    def test_compute_hash_deterministic(self) -> None:
        """Hash is deterministic for same inputs."""
        settings = make_settings()
        agent = JobProcessorAgent(settings)
        h1 = agent._compute_hash("Stripe", "SWE", "desc")
        h2 = agent._compute_hash("Stripe", "SWE", "desc")
        assert h1 == h2
        assert len(h1) == 64

    @pytest.mark.asyncio
    async def test_skips_invalid_posting(self) -> None:
        """HTML content identified as landing page is skipped."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="test",
            )
        )
        state.raw_jobs = [_make_raw_job_html()]

        fake_extracted = ExtractedJob(
            title="Careers at Acme",
            jd_text="We are hiring across multiple teams...",
            is_valid_posting=False,
        )

        with patch.object(
            JobProcessorAgent,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=fake_extracted,
        ):
            agent = JobProcessorAgent(settings)
            result = await agent.run(state)

        assert len(result.normalized_jobs) == 0

    @pytest.mark.asyncio
    async def test_accepts_valid_posting(self) -> None:
        """HTML content identified as valid posting is processed."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="test",
            )
        )
        state.raw_jobs = [_make_raw_job_html()]

        fake_extracted = ExtractedJob(
            title="Senior Python Developer",
            jd_text="We need a senior Python developer with 5+ years...",
            is_valid_posting=True,
            location="San Francisco",
            required_skills=["Python", "Django"],
        )

        with patch.object(
            JobProcessorAgent,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=fake_extracted,
        ):
            agent = JobProcessorAgent(settings)
            result = await agent.run(state)

        assert len(result.normalized_jobs) == 1
        assert result.normalized_jobs[0].title == "Senior Python Developer"

    @pytest.mark.asyncio
    async def test_json_extracts_posted_date_iso(self) -> None:
        """ATS JSON with ISO 8601 updated_at populates posted_date."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(resume_path=Path("/tmp/test.pdf"), preferences_text="test")
        )
        raw = RawJob(
            company_id=uuid4(),
            company_name="Acme",
            raw_json={
                "title": "SWE",
                "content": "Build things",
                "location": {"name": "NYC"},
                "absolute_url": "https://acme.com/jobs/1",
                "updated_at": "2025-06-15T10:30:00Z",
            },
            source_url="https://acme.com/jobs",
            scrape_strategy="api",
            source_confidence=0.9,
        )
        state.raw_jobs = [raw]

        agent = JobProcessorAgent(settings)
        result = await agent.run(state)

        assert len(result.normalized_jobs) == 1
        assert result.normalized_jobs[0].posted_date == date(2025, 6, 15)

    @pytest.mark.asyncio
    async def test_json_extracts_posted_date_unix_ms(self) -> None:
        """ATS JSON with Unix ms timestamp (Lever) populates posted_date."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(resume_path=Path("/tmp/test.pdf"), preferences_text="test")
        )
        raw = RawJob(
            company_id=uuid4(),
            company_name="LeverCo",
            raw_json={
                "title": "PM",
                "content": "Product management role",
                "createdAt": 1718400000000,  # 2024-06-15 approx
            },
            source_url="https://lever.co/jobs",
            scrape_strategy="api",
            source_confidence=0.9,
        )
        state.raw_jobs = [raw]

        agent = JobProcessorAgent(settings)
        result = await agent.run(state)

        assert len(result.normalized_jobs) == 1
        assert result.normalized_jobs[0].posted_date is not None

    @pytest.mark.asyncio
    async def test_json_apply_url_fallback_chain(self) -> None:
        """JSON apply_url falls through chain: applicationUrl -> source_url."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(resume_path=Path("/tmp/test.pdf"), preferences_text="test")
        )
        raw = RawJob(
            company_id=uuid4(),
            company_name="AshbyCo",
            raw_json={
                "title": "SWE",
                "content": "Build features",
                "applicationUrl": "https://ashby.co/apply/123",
            },
            source_url="https://ashby.co/jobs",
            scrape_strategy="api",
            source_confidence=0.9,
        )
        state.raw_jobs = [raw]

        agent = JobProcessorAgent(settings)
        result = await agent.run(state)

        assert len(result.normalized_jobs) == 1
        assert "ashby.co/apply/123" in str(result.normalized_jobs[0].apply_url)

    @pytest.mark.asyncio
    async def test_html_extracts_apply_url_from_llm(self) -> None:
        """HTML processing uses LLM-extracted apply_url when available."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(resume_path=Path("/tmp/test.pdf"), preferences_text="test")
        )
        state.raw_jobs = [_make_raw_job_html()]

        fake_extracted = ExtractedJob(
            title="Senior Dev",
            jd_text="Looking for a senior dev...",
            is_valid_posting=True,
            apply_url="https://acme.com/apply/specific-job-42",
            posted_date="2025-07-01",
        )

        with patch.object(
            JobProcessorAgent,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=fake_extracted,
        ):
            agent = JobProcessorAgent(settings)
            result = await agent.run(state)

        assert len(result.normalized_jobs) == 1
        assert "specific-job-42" in str(result.normalized_jobs[0].apply_url)
        assert result.normalized_jobs[0].posted_date == date(2025, 7, 1)

    @pytest.mark.asyncio
    async def test_html_falls_back_to_source_url(self) -> None:
        """HTML processing falls back to source_url when LLM returns no apply_url."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(resume_path=Path("/tmp/test.pdf"), preferences_text="test")
        )
        state.raw_jobs = [_make_raw_job_html()]

        fake_extracted = ExtractedJob(
            title="Dev",
            jd_text="Looking for a dev...",
            is_valid_posting=True,
            apply_url=None,
        )

        with patch.object(
            JobProcessorAgent,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=fake_extracted,
        ):
            agent = JobProcessorAgent(settings)
            result = await agent.run(state)

        assert len(result.normalized_jobs) == 1
        assert "acme.com/careers" in str(result.normalized_jobs[0].apply_url)

    def test_normalize_remote_type_variants(self) -> None:
        """_normalize_remote_type maps common variants to valid enum values."""
        assert _normalize_remote_type("on-site") == "onsite"
        assert _normalize_remote_type("On-Site") == "onsite"
        assert _normalize_remote_type("on_site") == "onsite"
        assert _normalize_remote_type("in-office") == "onsite"
        assert _normalize_remote_type("hybrid") == "hybrid"
        assert _normalize_remote_type("remote") == "remote"
        assert _normalize_remote_type("fully remote") == "remote"
        assert _normalize_remote_type("wfh") == "remote"
        assert _normalize_remote_type("unknown") == "unknown"
        assert _normalize_remote_type("garbage") == "unknown"
        assert _normalize_remote_type("  Remote  ") == "remote"

    @pytest.mark.asyncio
    async def test_html_normalizes_remote_type(self) -> None:
        """HTML processing normalizes LLM remote_type to valid enum value."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(resume_path=Path("/tmp/test.pdf"), preferences_text="test")
        )
        state.raw_jobs = [_make_raw_job_html()]

        fake_extracted = ExtractedJob(
            title="Remote Dev",
            jd_text="Looking for a remote dev...",
            is_valid_posting=True,
            remote_type="on-site",  # LLM returns hyphenated form
        )

        with patch.object(
            JobProcessorAgent,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=fake_extracted,
        ):
            agent = JobProcessorAgent(settings)
            result = await agent.run(state)

        assert len(result.normalized_jobs) == 1
        assert result.normalized_jobs[0].remote_type == "onsite"
