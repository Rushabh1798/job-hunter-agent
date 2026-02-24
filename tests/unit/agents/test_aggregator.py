"""Tests for aggregator agent."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from job_hunter_agents.agents.aggregator import AggregatorAgent
from job_hunter_core.models.job import FitReport, NormalizedJob, ScoredJob
from job_hunter_core.models.run import RunConfig
from job_hunter_core.state import PipelineState


def _make_settings(output_dir: Path) -> AsyncMock:
    """Create mock settings."""
    settings = AsyncMock()
    settings.anthropic_api_key.get_secret_value.return_value = "test-key"
    settings.output_dir = output_dir
    settings.max_cost_per_run_usd = 5.0
    settings.warn_cost_threshold_usd = 2.0
    return settings


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
            settings = _make_settings(Path(tmpdir))
            state = PipelineState(
                config=RunConfig(
                    resume_path=Path("/tmp/test.pdf"),
                    preferences_text="test",
                    output_formats=["csv"],
                )
            )
            state.scored_jobs = [_make_scored_job()]

            with (
                patch("job_hunter_agents.agents.base.AsyncAnthropic"),
                patch("job_hunter_agents.agents.base.instructor"),
            ):
                agent = AggregatorAgent(settings)
                result = await agent.run(state)

            assert result.run_result is not None
            assert any(
                str(f).endswith(".csv") for f in result.run_result.output_files
            )

    @pytest.mark.asyncio
    async def test_writes_xlsx(self) -> None:
        """Agent writes Excel output file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = _make_settings(Path(tmpdir))
            state = PipelineState(
                config=RunConfig(
                    resume_path=Path("/tmp/test.pdf"),
                    preferences_text="test",
                    output_formats=["xlsx"],
                )
            )
            state.scored_jobs = [_make_scored_job()]

            with (
                patch("job_hunter_agents.agents.base.AsyncAnthropic"),
                patch("job_hunter_agents.agents.base.instructor"),
            ):
                agent = AggregatorAgent(settings)
                result = await agent.run(state)

            assert result.run_result is not None
            assert any(
                str(f).endswith(".xlsx") for f in result.run_result.output_files
            )

    @pytest.mark.asyncio
    async def test_empty_scored_jobs(self) -> None:
        """Agent handles empty scored jobs without error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = _make_settings(Path(tmpdir))
            state = PipelineState(
                config=RunConfig(
                    resume_path=Path("/tmp/test.pdf"),
                    preferences_text="test",
                    output_formats=["csv"],
                )
            )
            state.scored_jobs = []

            with (
                patch("job_hunter_agents.agents.base.AsyncAnthropic"),
                patch("job_hunter_agents.agents.base.instructor"),
            ):
                agent = AggregatorAgent(settings)
                result = await agent.run(state)

            assert result.run_result is not None
            assert result.run_result.status == "partial"

    def test_build_rows(self) -> None:
        """Row building includes all expected columns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = _make_settings(Path(tmpdir))
            state = PipelineState(
                config=RunConfig(
                    resume_path=Path("/tmp/test.pdf"),
                    preferences_text="test",
                )
            )
            state.scored_jobs = [_make_scored_job()]

            with (
                patch("job_hunter_agents.agents.base.AsyncAnthropic"),
                patch("job_hunter_agents.agents.base.instructor"),
            ):
                agent = AggregatorAgent(settings)
                rows = agent._build_rows(state)

            assert len(rows) == 1
            assert "Rank" in rows[0]
            assert "Score" in rows[0]
            assert "Apply URL" in rows[0]
