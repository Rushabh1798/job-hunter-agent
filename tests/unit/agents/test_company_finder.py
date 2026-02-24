"""Tests for company finder agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from job_hunter_agents.agents.company_finder import (
    CompanyFinderAgent,
)
from job_hunter_core.exceptions import FatalAgentError
from job_hunter_core.models.candidate import CandidateProfile, SearchPreferences, Skill
from job_hunter_core.models.run import RunConfig
from job_hunter_core.state import PipelineState


def _make_settings() -> AsyncMock:
    """Create mock settings."""
    settings = AsyncMock()
    settings.anthropic_api_key.get_secret_value.return_value = "test-key"
    settings.sonnet_model = "claude-sonnet-4-5-20250514"
    settings.tavily_api_key.get_secret_value.return_value = "tavily-key"
    settings.max_cost_per_run_usd = 5.0
    settings.warn_cost_threshold_usd = 2.0
    return settings


def _make_state_with_profile() -> PipelineState:
    """Create state with profile and preferences."""
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
        skills=[Skill(name="Python")],
        raw_text="test",
        content_hash="abc",
    )
    state.preferences = SearchPreferences(
        target_titles=["SWE"],
        raw_text="test",
    )
    return state


@pytest.mark.unit
class TestCompanyFinderAgent:
    """Test CompanyFinderAgent."""

    @pytest.mark.asyncio
    async def test_raises_without_profile(self) -> None:
        """Agent raises FatalAgentError if profile missing."""
        settings = _make_settings()
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="test",
            )
        )

        with (
            patch("job_hunter_agents.agents.base.AsyncAnthropic"),
            patch("job_hunter_agents.agents.base.instructor"),
        ):
            agent = CompanyFinderAgent(settings)
            with pytest.raises(FatalAgentError):
                await agent.run(state)

    @pytest.mark.asyncio
    async def test_uses_preferred_companies(self) -> None:
        """Agent uses preferred_companies from prefs if available."""
        settings = _make_settings()
        state = _make_state_with_profile()
        assert state.preferences is not None
        state.preferences.preferred_companies = ["Stripe", "Figma"]

        with (
            patch.object(
                CompanyFinderAgent,
                "_validate_and_build",
                new_callable=AsyncMock,
            ) as mock_validate,
            patch("job_hunter_agents.agents.base.AsyncAnthropic"),
            patch("job_hunter_agents.agents.base.instructor"),
        ):
            from job_hunter_core.models.company import ATSType, CareerPage, Company

            mock_validate.return_value = Company(
                name="Stripe",
                domain="stripe.com",
                career_page=CareerPage(
                    url="https://stripe.com/jobs",
                    ats_type=ATSType.UNKNOWN,
                ),
            )
            agent = CompanyFinderAgent(settings)
            result = await agent.run(state)

        assert len(result.companies) > 0

    @pytest.mark.asyncio
    async def test_ats_detection(self) -> None:
        """ATS detection identifies Greenhouse URLs."""
        settings = _make_settings()

        with (
            patch("job_hunter_agents.agents.base.AsyncAnthropic"),
            patch("job_hunter_agents.agents.base.instructor"),
        ):
            agent = CompanyFinderAgent(settings)
            from job_hunter_core.models.company import ATSType

            ats_type, strategy = await agent._detect_ats(
                "https://boards.greenhouse.io/stripe"
            )
            assert ats_type == ATSType.GREENHOUSE
            assert strategy == "api"

    @pytest.mark.asyncio
    async def test_ats_detection_unknown(self) -> None:
        """Unknown URLs get crawl4ai strategy."""
        settings = _make_settings()

        with (
            patch("job_hunter_agents.agents.base.AsyncAnthropic"),
            patch("job_hunter_agents.agents.base.instructor"),
        ):
            agent = CompanyFinderAgent(settings)
            from job_hunter_core.models.company import ATSType

            ats_type, strategy = await agent._detect_ats(
                "https://company.com/careers"
            )
            assert ats_type == ATSType.UNKNOWN
            assert strategy == "crawl4ai"
