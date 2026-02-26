"""Tests for preferences parser agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from job_hunter_agents.agents.prefs_parser import PrefsParserAgent
from job_hunter_core.models.candidate import (
    CandidateProfile,
    SearchPreferences,
    Skill,
)
from job_hunter_core.models.run import RunConfig
from job_hunter_core.state import PipelineState
from tests.mocks.mock_settings import make_settings


@pytest.mark.unit
class TestPrefsParserAgent:
    """Test PrefsParserAgent."""

    @pytest.mark.asyncio
    async def test_run_parses_preferences(self) -> None:
        """Agent parses freeform text into SearchPreferences."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="Senior ML roles, remote, startups, $180k+",
            )
        )
        prefs = SearchPreferences(
            target_titles=["Senior ML Engineer"],
            remote_preference="remote",
            org_types=["startup"],
            min_salary=180000,
            raw_text="",
        )

        with patch.object(
            PrefsParserAgent,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=prefs,
        ):
            agent = PrefsParserAgent(settings)
            result = await agent.run(state)

        assert result.preferences is not None
        assert result.preferences.target_titles == ["Senior ML Engineer"]
        assert result.preferences.raw_text == state.config.preferences_text

    @pytest.mark.asyncio
    async def test_run_preserves_raw_text(self) -> None:
        """Agent sets raw_text to the original preferences text."""
        settings = make_settings()
        original_text = "I want remote Python jobs"
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text=original_text,
            )
        )
        prefs = SearchPreferences(raw_text="")

        with patch.object(
            PrefsParserAgent,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=prefs,
        ):
            agent = PrefsParserAgent(settings)
            result = await agent.run(state)

        assert result.preferences is not None
        assert result.preferences.raw_text == original_text

    @pytest.mark.asyncio
    async def test_enriches_preferences_from_profile(self) -> None:
        """Agent fills missing pref fields from resume profile."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="remote Python jobs",
            )
        )
        state.profile = CandidateProfile(
            name="Jane",
            email="jane@test.com",
            years_of_experience=5.0,
            skills=[Skill(name="Python")],
            current_title="Senior Backend Engineer",
            location="San Francisco, CA",
            seniority_level="senior",
            industries=["Technology", "FinTech"],
            past_titles=["Backend Engineer", "SWE"],
            raw_text="test",
            content_hash="abc",
        )
        prefs = SearchPreferences(raw_text="")

        with patch.object(
            PrefsParserAgent,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=prefs,
        ):
            agent = PrefsParserAgent(settings)
            result = await agent.run(state)

        assert result.preferences is not None
        assert result.preferences.preferred_locations == ["San Francisco, CA"]
        assert "Senior Backend Engineer" in result.preferences.target_titles
        assert result.preferences.target_seniority == ["senior"]
        assert "Technology" in result.preferences.preferred_industries

    @pytest.mark.asyncio
    async def test_enrichment_preserves_existing_values(self) -> None:
        """Enrichment does not overwrite fields that are already populated."""
        settings = make_settings()
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="ML roles in NYC",
            )
        )
        state.profile = CandidateProfile(
            name="Jane",
            email="jane@test.com",
            years_of_experience=5.0,
            skills=[Skill(name="Python")],
            current_title="SWE",
            location="London, UK",
            raw_text="test",
            content_hash="abc",
        )
        prefs = SearchPreferences(
            target_titles=["ML Engineer"],
            preferred_locations=["New York"],
            raw_text="",
        )

        with patch.object(
            PrefsParserAgent,
            "_call_llm",
            new_callable=AsyncMock,
            return_value=prefs,
        ):
            agent = PrefsParserAgent(settings)
            result = await agent.run(state)

        assert result.preferences is not None
        assert result.preferences.preferred_locations == ["New York"]
        assert result.preferences.target_titles == ["ML Engineer"]


@pytest.mark.unit
class TestEnrichPreferences:
    """Test _enrich_preferences static method in isolation."""

    def test_fills_all_empty_fields(self) -> None:
        """All empty fields filled from profile."""
        prefs = SearchPreferences(raw_text="test")
        profile = CandidateProfile(
            name="Jane",
            email="j@test.com",
            years_of_experience=5.0,
            skills=[Skill(name="Python")],
            current_title="Staff Engineer",
            location="Bangalore",
            seniority_level="staff",
            industries=["SaaS"],
            past_titles=["Senior Engineer", "Engineer"],
            raw_text="test",
            content_hash="abc",
        )
        result = PrefsParserAgent._enrich_preferences(prefs, profile)

        assert result.preferred_locations == ["Bangalore"]
        assert result.target_titles == ["Staff Engineer", "Senior Engineer", "Engineer"]
        assert result.target_seniority == ["staff"]
        assert result.preferred_industries == ["SaaS"]

    def test_no_profile_data(self) -> None:
        """No-op when profile has no useful data."""
        prefs = SearchPreferences(raw_text="test")
        profile = CandidateProfile(
            name="Jane",
            email="j@test.com",
            years_of_experience=0.0,
            skills=[],
            raw_text="test",
            content_hash="abc",
        )
        result = PrefsParserAgent._enrich_preferences(prefs, profile)

        assert result.preferred_locations == []
        assert result.target_titles == []
        assert result.target_seniority == []
