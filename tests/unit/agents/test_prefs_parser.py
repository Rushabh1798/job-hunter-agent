"""Tests for preferences parser agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from job_hunter_agents.agents.prefs_parser import PrefsParserAgent
from job_hunter_core.models.candidate import SearchPreferences
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
