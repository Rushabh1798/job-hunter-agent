"""Tests for jobs scorer agent."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from job_hunter_agents.agents.jobs_scorer import (
    BatchScoreResult,
    JobScore,
    JobsScorerAgent,
    _currency_symbol,
)
from job_hunter_core.models.candidate import CandidateProfile, SearchPreferences, Skill
from job_hunter_core.models.company import ATSType, CareerPage, Company, CompanyTier
from job_hunter_core.models.job import NormalizedJob
from job_hunter_core.models.run import RunConfig
from job_hunter_core.state import PipelineState
from tests.mocks.mock_settings import make_settings


def _make_normalized_job(
    title: str = "SWE",
    salary_min: int | None = None,
    salary_max: int | None = None,
    currency: str | None = None,
) -> NormalizedJob:
    """Create a test normalized job."""
    return NormalizedJob(
        raw_job_id=uuid4(),
        company_id=uuid4(),
        company_name="TestCo",
        title=title,
        jd_text="Looking for a great developer...",
        apply_url="https://testco.com/apply",
        content_hash="hash123",
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
    )


def _make_state_with_jobs(
    currency: str = "USD",
    min_salary: int | None = None,
    max_salary: int | None = None,
) -> PipelineState:
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
    state.preferences = SearchPreferences(
        raw_text="test",
        currency=currency,
        min_salary=min_salary,
        max_salary=max_salary,
    )
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
        assert "Posted Date:" in block
        assert "Company Tier:" in block

    def test_format_jobs_block_with_posted_date(self) -> None:
        """Jobs block includes posted_date when set."""
        settings = make_settings()
        agent = JobsScorerAgent(settings)
        job = _make_normalized_job("Dev")
        job.posted_date = date(2025, 7, 1)
        block = agent._format_jobs_block([job])

        assert "Posted Date: 2025-07-01" in block

    def test_format_jobs_block_with_company_tier(self) -> None:
        """Jobs block includes company tier from state lookup."""
        settings = make_settings()
        agent = JobsScorerAgent(settings)
        company_id = uuid4()
        job = NormalizedJob(
            raw_job_id=uuid4(),
            company_id=company_id,
            company_name="BigTech",
            title="SWE",
            jd_text="Build stuff",
            apply_url="https://bigtech.com/apply",
            content_hash="h1",
        )
        state = PipelineState(
            config=RunConfig(resume_path=Path("/tmp/t.pdf"), preferences_text="t"),
        )
        state.companies = [
            Company(
                id=company_id,
                name="BigTech",
                domain="bigtech.com",
                career_page=CareerPage(url="https://bigtech.com/careers", ats_type=ATSType.UNKNOWN),
                tier=CompanyTier.TIER_1,
            )
        ]
        block = agent._format_jobs_block([job], state=state)

        assert "Company Tier: tier_1" in block

    def test_format_jobs_block_with_inr_salary(self) -> None:
        """Jobs block formats INR salary with rupee symbol."""
        settings = make_settings()
        agent = JobsScorerAgent(settings)
        jobs = [
            _make_normalized_job(
                "SWE",
                salary_min=2000000,
                salary_max=3500000,
                currency="INR",
            )
        ]
        block = agent._format_jobs_block(jobs)

        assert "₹2,000,000" in block
        assert "₹3,500,000" in block
        assert "INR" in block
        assert "$" not in block

    @pytest.mark.asyncio
    async def test_inr_salary_range_in_prompt(self) -> None:
        """INR salary range uses rupee symbol in scorer prompt."""
        settings = make_settings()
        state = _make_state_with_jobs(
            currency="INR",
            min_salary=3500000,
            max_salary=5000000,
        )

        captured_messages: list[dict[str, str]] = []

        async def _capture_llm(
            messages: list[dict[str, str]], **kwargs: object
        ) -> BatchScoreResult:
            captured_messages.extend(messages)
            return BatchScoreResult(scores=[])

        with patch.object(
            JobsScorerAgent,
            "_call_llm",
            side_effect=_capture_llm,
        ):
            agent = JobsScorerAgent(settings)
            await agent.run(state)

        prompt_content = captured_messages[0]["content"]
        assert "₹3,500,000" in prompt_content
        assert "₹5,000,000" in prompt_content
        assert "INR" in prompt_content


@pytest.mark.unit
class TestRelevancePrefilter:
    """Test _relevance_prefilter method."""

    def test_excludes_non_engineering_titles(self) -> None:
        """Non-engineering roles like Account Executive are filtered out."""
        settings = make_settings()
        agent = JobsScorerAgent(settings)
        profile = CandidateProfile(
            name="Jane",
            email="jane@test.com",
            years_of_experience=5.0,
            skills=[Skill(name="Python")],
            raw_text="test",
            content_hash="abc",
        )
        prefs = SearchPreferences(raw_text="test")
        jobs = [
            _make_normalized_job("Account Executive"),
            _make_normalized_job("Senior Software Engineer"),
            _make_normalized_job("Sales Representative"),
            _make_normalized_job("Machine Learning Engineer"),
        ]
        result = agent._relevance_prefilter(jobs, profile, prefs)
        titles = [j.title for j in result]

        assert "Account Executive" not in titles
        assert "Sales Representative" not in titles
        assert "Senior Software Engineer" in titles
        assert "Machine Learning Engineer" in titles

    def test_ranks_by_keyword_relevance(self) -> None:
        """Jobs with matching title keywords rank higher."""
        settings = make_settings()
        agent = JobsScorerAgent(settings)
        profile = CandidateProfile(
            name="Jane",
            email="jane@test.com",
            years_of_experience=5.0,
            skills=[Skill(name="Python"), Skill(name="Machine Learning")],
            current_title="ML Engineer",
            raw_text="test",
            content_hash="abc",
        )
        prefs = SearchPreferences(raw_text="test")
        jobs = [
            _make_normalized_job("Frontend Designer"),
            _make_normalized_job("ML Engineer"),
        ]
        result = agent._relevance_prefilter(jobs, profile, prefs)

        assert result[0].title == "ML Engineer"

    def test_respects_per_company_limit(self) -> None:
        """Pre-filter limits jobs per company."""
        settings = make_settings(max_jobs_per_company=2)
        agent = JobsScorerAgent(settings)
        company_id = uuid4()
        jobs = []
        for i in range(5):
            job = _make_normalized_job(f"Engineer {i}")
            job.company_id = company_id
            job.company_name = "SameCo"
            jobs.append(job)
        result = agent._relevance_prefilter(jobs, None, None)

        assert len(result) == 2

    def test_respects_top_k_cap(self) -> None:
        """Pre-filter caps total jobs at top_k_semantic."""
        settings = make_settings(top_k_semantic=3)
        agent = JobsScorerAgent(settings)
        jobs = [_make_normalized_job(f"Role {i}") for i in range(10)]
        # Give each a different company to avoid per-company limit
        for i, job in enumerate(jobs):
            job.company_name = f"Co{i}"
        result = agent._relevance_prefilter(jobs, None, None)

        assert len(result) == 3

    def test_excludes_non_matching_locations(self) -> None:
        """Jobs in non-matching locations are hard-excluded."""
        settings = make_settings()
        agent = JobsScorerAgent(settings)
        profile = CandidateProfile(
            name="Jane",
            email="jane@test.com",
            years_of_experience=5.0,
            skills=[Skill(name="Python")],
            raw_text="test",
            content_hash="abc",
        )
        prefs = SearchPreferences(
            raw_text="test",
            preferred_locations=["india", "bangalore"],
        )
        india_job = _make_normalized_job("ML Engineer")
        india_job.location = "Bangalore, India"
        india_job.company_name = "Co1"
        sf_job = _make_normalized_job("ML Engineer")
        sf_job.location = "San Francisco, CA, United States"
        sf_job.company_name = "Co2"
        remote_job = _make_normalized_job("ML Engineer")
        remote_job.location = "New York, USA"
        remote_job.remote_type = "remote"
        remote_job.company_name = "Co3"
        no_loc_job = _make_normalized_job("ML Engineer")
        no_loc_job.location = ""
        no_loc_job.company_name = "Co4"

        jobs = [india_job, sf_job, remote_job, no_loc_job]
        result = agent._relevance_prefilter(jobs, profile, prefs)
        locations = [j.location for j in result]

        assert "Bangalore, India" in locations
        assert "San Francisco, CA, United States" not in locations
        # Remote jobs kept despite non-matching location
        assert "New York, USA" in locations
        # Empty location excluded when prefs set (unknown location = not matching)
        assert "" not in locations


@pytest.mark.unit
class TestCurrencySymbol:
    """Test _currency_symbol helper."""

    def test_usd(self) -> None:
        """USD returns dollar sign."""
        assert _currency_symbol("USD") == "$"

    def test_inr(self) -> None:
        """INR returns rupee sign."""
        assert _currency_symbol("INR") == "₹"

    def test_eur(self) -> None:
        """EUR returns euro sign."""
        assert _currency_symbol("EUR") == "€"

    def test_unknown_currency(self) -> None:
        """Unknown currency returns code with space."""
        assert _currency_symbol("JPY") == "JPY "

    def test_case_insensitive(self) -> None:
        """Currency code lookup is case-insensitive."""
        assert _currency_symbol("inr") == "₹"
