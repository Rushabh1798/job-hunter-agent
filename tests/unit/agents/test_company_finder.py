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
from job_hunter_core.models.company import CompanyTier
from job_hunter_core.models.run import RunConfig
from job_hunter_core.state import PipelineState
from tests.mocks.mock_settings import make_settings


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
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="test",
            )
        )

        agent = CompanyFinderAgent(settings)
        with pytest.raises(FatalAgentError):
            await agent.run(state)

    @pytest.mark.asyncio
    async def test_uses_preferred_companies(self) -> None:
        """Agent uses preferred_companies from prefs if available."""
        settings = make_settings()
        state = _make_state_with_profile()
        assert state.preferences is not None
        state.preferences.preferred_companies = ["Stripe", "Figma"]

        with patch.object(
            CompanyFinderAgent,
            "_validate_and_build",
            new_callable=AsyncMock,
        ) as mock_validate:
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
        settings = make_settings()

        agent = CompanyFinderAgent(settings)
        from job_hunter_core.models.company import ATSType

        ats_type, strategy = await agent._detect_ats("https://boards.greenhouse.io/stripe")
        assert ats_type == ATSType.GREENHOUSE
        assert strategy == "api"

    @pytest.mark.asyncio
    async def test_ats_detection_unknown(self) -> None:
        """Unknown URLs get crawl4ai strategy."""
        settings = make_settings()

        agent = CompanyFinderAgent(settings)
        from job_hunter_core.models.company import ATSType

        ats_type, strategy = await agent._detect_ats("https://company.com/careers")
        assert ats_type == ATSType.UNKNOWN
        assert strategy == "crawl4ai"

    def test_map_tier_valid_values(self) -> None:
        """Valid tier strings map to CompanyTier enum."""
        assert CompanyFinderAgent._map_tier("tier_1") == CompanyTier.TIER_1
        assert CompanyFinderAgent._map_tier("tier_2") == CompanyTier.TIER_2
        assert CompanyFinderAgent._map_tier("tier_3") == CompanyTier.TIER_3
        assert CompanyFinderAgent._map_tier("startup") == CompanyTier.STARTUP

    def test_map_tier_case_insensitive(self) -> None:
        """Tier mapping handles case variations."""
        assert CompanyFinderAgent._map_tier("TIER_1") == CompanyTier.TIER_1
        assert CompanyFinderAgent._map_tier(" Tier_2 ") == CompanyTier.TIER_2

    def test_map_tier_unknown_fallback(self) -> None:
        """Invalid tier strings fall back to UNKNOWN."""
        assert CompanyFinderAgent._map_tier("mega_corp") == CompanyTier.UNKNOWN
        assert CompanyFinderAgent._map_tier("") == CompanyTier.UNKNOWN


@pytest.mark.unit
class TestGetSeedCompanies:
    """Test ATS seed company selection."""

    def test_returns_companies_matching_industries(self) -> None:
        """Seed companies are filtered and scored by industry tags."""
        from job_hunter_agents.data.ats_seed_companies import match_seed_companies

        results = match_seed_companies(
            industries=["Technology", "AI"],
            locations=["Bangalore"],
            excluded_names=set(),
            limit=5,
        )
        assert len(results) > 0
        assert len(results) <= 5
        # All results should have valid ATS types
        for company in results:
            assert company.ats in ("greenhouse", "lever", "ashby")

    def test_respects_excluded_names(self) -> None:
        """Excluded companies are not returned."""
        from job_hunter_agents.data.ats_seed_companies import match_seed_companies

        results = match_seed_companies(
            industries=["Technology"],
            locations=["Bangalore"],
            excluded_names={"Postman", "Zscaler"},
            limit=20,
        )
        names = {c.name for c in results}
        assert "Postman" not in names
        assert "Zscaler" not in names

    def test_limit_respected(self) -> None:
        """Returns at most `limit` companies."""
        from job_hunter_agents.data.ats_seed_companies import match_seed_companies

        results = match_seed_companies(
            industries=["Technology"],
            locations=["Remote"],
            excluded_names=set(),
            limit=3,
        )
        assert len(results) <= 3
