"""Tests for aggregator agent."""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from job_hunter_agents.agents.aggregator import AggregatorAgent
from job_hunter_core.models.company import ATSType, CareerPage, Company, CompanyTier
from job_hunter_core.models.job import FitReport, NormalizedJob, ScoredJob
from job_hunter_core.models.run import RunConfig
from job_hunter_core.state import PipelineState
from tests.mocks.mock_settings import make_settings


def _make_scored_job(rank: int = 1, score: int = 85) -> ScoredJob:
    """Create a test scored job."""
    job = NormalizedJob(
        raw_job_id=uuid4(),
        company_id=uuid4(),
        company_name="TestCo",
        title="SWE",
        jd_text="Great job",
        apply_url="https://testco.com/apply",
        content_hash="hash123",
    )
    return ScoredJob(
        job=job,
        fit_report=FitReport(
            score=score,
            skill_overlap=["Python"],
            skill_gaps=["Go"],
            seniority_match=True,
            location_match=True,
            org_type_match=True,
            summary="Good fit overall",
            recommendation="good_match",
            confidence=0.85,
        ),
        rank=rank,
    )


@pytest.mark.unit
class TestAggregatorAgent:
    """Test AggregatorAgent."""

    @pytest.mark.asyncio
    async def test_writes_csv(self) -> None:
        """Agent writes CSV output file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = make_settings(output_dir=Path(tmpdir))
            state = PipelineState(
                config=RunConfig(
                    resume_path=Path("/tmp/test.pdf"),
                    preferences_text="test",
                    output_formats=["csv"],
                )
            )
            state.scored_jobs = [_make_scored_job()]

            agent = AggregatorAgent(settings)
            result = await agent.run(state)

            assert result.run_result is not None
            assert any(str(f).endswith(".csv") for f in result.run_result.output_files)

    @pytest.mark.asyncio
    async def test_writes_xlsx(self) -> None:
        """Agent writes Excel output file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = make_settings(output_dir=Path(tmpdir))
            state = PipelineState(
                config=RunConfig(
                    resume_path=Path("/tmp/test.pdf"),
                    preferences_text="test",
                    output_formats=["xlsx"],
                )
            )
            state.scored_jobs = [_make_scored_job()]

            agent = AggregatorAgent(settings)
            result = await agent.run(state)

            assert result.run_result is not None
            assert any(str(f).endswith(".xlsx") for f in result.run_result.output_files)

    @pytest.mark.asyncio
    async def test_empty_scored_jobs(self) -> None:
        """Agent handles empty scored jobs without error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = make_settings(output_dir=Path(tmpdir))
            state = PipelineState(
                config=RunConfig(
                    resume_path=Path("/tmp/test.pdf"),
                    preferences_text="test",
                    output_formats=["csv"],
                )
            )
            state.scored_jobs = []

            agent = AggregatorAgent(settings)
            result = await agent.run(state)

            assert result.run_result is not None
            assert result.run_result.status == "partial"

    def test_build_rows(self) -> None:
        """Row building includes all expected columns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = make_settings(output_dir=Path(tmpdir))
            state = PipelineState(
                config=RunConfig(
                    resume_path=Path("/tmp/test.pdf"),
                    preferences_text="test",
                )
            )
            state.scored_jobs = [_make_scored_job()]

            agent = AggregatorAgent(settings)
            rows = agent._build_rows(state)

            assert len(rows) == 1
            assert "Rank" in rows[0]
            assert "Score" in rows[0]
            assert "Apply URL" in rows[0]
            assert "Company Tier" in rows[0]

    def test_build_rows_with_tier_lookup(self) -> None:
        """Company Tier column uses tier from state.companies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = make_settings(output_dir=Path(tmpdir))
            company_id = uuid4()
            state = PipelineState(
                config=RunConfig(
                    resume_path=Path("/tmp/test.pdf"),
                    preferences_text="test",
                )
            )
            state.companies = [
                Company(
                    id=company_id,
                    name="TestCo",
                    domain="testco.com",
                    career_page=CareerPage(
                        url="https://testco.com/careers",
                        ats_type=ATSType.UNKNOWN,
                    ),
                    tier=CompanyTier.TIER_2,
                )
            ]
            job = NormalizedJob(
                raw_job_id=uuid4(),
                company_id=company_id,
                company_name="TestCo",
                title="SWE",
                jd_text="Great job",
                apply_url="https://testco.com/apply",
                content_hash="hash123",
            )
            state.scored_jobs = [
                ScoredJob(
                    job=job,
                    fit_report=FitReport(
                        score=85,
                        skill_overlap=["Python"],
                        skill_gaps=[],
                        seniority_match=True,
                        location_match=True,
                        org_type_match=True,
                        summary="Good fit",
                        recommendation="good_match",
                        confidence=0.85,
                    ),
                    rank=1,
                )
            ]

            agent = AggregatorAgent(settings)
            rows = agent._build_rows(state)

            assert rows[0]["Company Tier"] == "tier_2"

    def test_format_salary_with_currency(self) -> None:
        """Salary formatting respects currency symbol."""
        result = AggregatorAgent._format_salary(2000000, 3500000, "INR")
        assert result == "₹2,000,000-₹3,500,000 INR"
        assert AggregatorAgent._format_salary(100000, 150000, "USD") == "$100,000-$150,000 USD"
        assert AggregatorAgent._format_salary(100000, None, "EUR") == "€100,000+ EUR"
        assert AggregatorAgent._format_salary(None, None, None) == ""
