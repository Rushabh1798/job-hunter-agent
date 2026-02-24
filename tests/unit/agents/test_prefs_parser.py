"""Tests for preferences parser agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from job_hunter_agents.agents.prefs_parser import PrefsParserAgent
from job_hunter_core.models.candidate import SearchPreferences
from job_hunter_core.models.run import RunConfig
from job_hunter_core.state import PipelineState


def _make_settings() -> AsyncMock:
    """Create mock settings."""
    settings = AsyncMock()
    settings.anthropic_api_key.get_secret_value.return_value = "test-key"
    settings.haiku_model = "claude-haiku-4-5-20251001"
    settings.max_cost_per_run_usd = 5.0
    settings.warn_cost_threshold_usd = 2.0
    return settings


@pytest.mark.unit
class TestPrefsParserAgent:
    """Test PrefsParserAgent."""

    @pytest.mark.asyncio
    async def test_run_parses_preferences(self) -> None:
        """Agent parses freeform text into SearchPreferences."""
        settings = _make_settings()
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

        with (
            patch.object(
                PrefsParserAgent,
                "_call_llm",
                new_callable=AsyncMock,
                return_value=prefs,
            ),
            patch("job_hunter_agents.agents.base.AsyncAnthropic"),
            patch("job_hunter_agents.agents.base.instructor"),
        ):
            agent = PrefsParserAgent(settings)
            result = await agent.run(state)

        assert result.preferences is not None
        assert result.preferences.target_titles == ["Senior ML Engineer"]
        assert result.preferences.raw_text == state.config.preferences_text

    @pytest.mark.asyncio
    async def test_run_preserves_raw_text(self) -> None:
        """Agent sets raw_text to the original preferences text."""
        settings = _make_settings()
        original_text = "I want remote Python jobs"
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text=original_text,
            )
        )
        prefs = SearchPreferences(raw_text="")

        with (
            patch.object(
                PrefsParserAgent,
                "_call_llm",
                new_callable=AsyncMock,
                return_value=prefs,
            ),
            patch("job_hunter_agents.agents.base.AsyncAnthropic"),
            patch("job_hunter_agents.agents.base.instructor"),
        ):
            agent = PrefsParserAgent(settings)
            result = await agent.run(state)

        assert result.preferences is not None
        assert result.preferences.raw_text == original_text
