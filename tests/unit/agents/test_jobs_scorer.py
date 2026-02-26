"""Tests for jobs scorer agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from job_hunter_agents.agents.jobs_scorer import (
    BatchScoreResult,
    JobScore,
    JobsScorerAgent,
)
from job_hunter_core.models.candidate import CandidateProfile, SearchPreferences, Skill
from job_hunter_core.models.job import NormalizedJob
from job_hunter_core.models.run import RunConfig
from job_hunter_core.state import PipelineState
from tests.mocks.mock_settings import make_settings


def _make_normalized_job(title: str = "SWE") -> NormalizedJob:
    """Create a test normalized job."""
    return NormalizedJob(
        raw_job_id=uuid4(),
        company_id=uuid4(),
        company_name="TestCo",
        title=title,
        jd_text="Looking for a great developer...",
        apply_url="https://testco.com/apply",
        content_hash="hash123",
    )


def _make_state_with_jobs() -> PipelineState:
    """Create state with profile, prefs, and jobs."""
    state = PipelineState(
        config=RunConfig(
            resume_path=Path("/tmp/test.pdf"),
            preferences_text="test",
        )
    )
    state.profile = CandidateProfile(
        name="Jane",
        email="jane@test.com",
        years_of_experience=5.0,
        skills=[Skill(name="Python"), Skill(name="Django")],
        raw_text="test",
        content_hash="abc",
    )
    state.preferences = SearchPreferences(raw_text="test")
    state.normalized_jobs = [
        _make_normalized_job("SWE"),
        _make_normalized_job("Senior SWE"),
    ]
    return state


@pytest.mark.unit
class TestJobsScorerAgent:
    """Test JobsScorerAgent."""

    @pytest.mark.asyncio
    async def test_scores_jobs(self) -> None:
        """Agent scores normalized jobs and filters by threshold."""
        settings = make_settings()
        state = _make_state_with_jobs()

        mock_result = BatchScoreResult(
            scores=[
                JobScore(
                    job_index=0,
                    score=75,
                    summary="Good fit",
                    recommendation="good_match",
                ),
                JobScore(
                    job_index=1,
                    score=85,
                    summary="Strong fit",
                    recommendation="strong_match",
                ),
            ]
        )

        with patch.object(
            JobsScorerAgent,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            agent = JobsScorerAgent(settings)
            result = await agent.run(state)

        assert len(result.scored_jobs) == 2
        assert result.scored_jobs[0].fit_report.score == 85
        assert result.scored_jobs[0].rank == 1

    @pytest.mark.asyncio
    async def test_filters_below_threshold(self) -> None:
        """Jobs below min_score_threshold are excluded."""
        settings = make_settings(min_score_threshold=80)
        state = _make_state_with_jobs()

        mock_result = BatchScoreResult(
            scores=[
                JobScore(
                    job_index=0,
                    score=50,
                    summary="Weak",
                    recommendation="mismatch",
                ),
                JobScore(
                    job_index=1,
                    score=85,
                    summary="Strong",
                    recommendation="strong_match",
                ),
            ]
        )

        with patch.object(
            JobsScorerAgent,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            agent = JobsScorerAgent(settings)
            result = await agent.run(state)

        assert len(result.scored_jobs) == 1
        assert result.scored_jobs[0].fit_report.score == 85

    @pytest.mark.asyncio
    async def test_skips_without_profile(self) -> None:
        """Agent returns early if profile is missing."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="test",
            )
        )

        agent = JobsScorerAgent(settings)
        result = await agent.run(state)

        assert len(result.scored_jobs) == 0

    def test_format_jobs_block(self) -> None:
        """Jobs block formatting includes all key fields."""
        settings = make_settings()
        agent = JobsScorerAgent(settings)
        jobs = [_make_normalized_job("Test Role")]
        block = agent._format_jobs_block(jobs)

        assert "Test Role" in block
        assert "TestCo" in block
        assert 'index="0"' in block
