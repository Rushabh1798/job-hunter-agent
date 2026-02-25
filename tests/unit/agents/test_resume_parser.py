"""Tests for resume parser agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from job_hunter_agents.agents.resume_parser import ResumeParserAgent
from job_hunter_core.models.candidate import CandidateProfile, Skill
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


def _make_state() -> PipelineState:
    """Create test pipeline state."""
    return PipelineState(
        config=RunConfig(
            resume_path=Path("/tmp/test_resume.pdf"),
            preferences_text="test prefs",
        )
    )


def _make_profile() -> CandidateProfile:
    """Create test profile."""
    return CandidateProfile(
        name="Jane Doe",
        email="jane@example.com",
        years_of_experience=5.0,
        skills=[Skill(name="Python"), Skill(name="ML")],
        raw_text="Test resume text",
        content_hash="abc123",
    )


@pytest.mark.unit
class TestResumeParserAgent:
    """Test ResumeParserAgent."""

    @pytest.mark.asyncio
    async def test_run_parses_resume(self) -> None:
        """Agent extracts profile from PDF and sets state.profile."""
        settings = _make_settings()
        state = _make_state()
        profile = _make_profile()

        with (
            patch("job_hunter_agents.agents.resume_parser.PDFParser") as mock_pdf_cls,
            patch.object(
                ResumeParserAgent,
                "_call_llm",
                new_callable=AsyncMock,
                return_value=profile,
            ),
            patch("job_hunter_agents.agents.base.AsyncAnthropic"),
            patch("job_hunter_agents.agents.base.instructor"),
        ):
            mock_pdf = mock_pdf_cls.return_value
            mock_pdf.extract_text = AsyncMock(return_value="Resume text here")

            agent = ResumeParserAgent(settings)
            result = await agent.run(state)

        assert result.profile is not None
        assert result.profile.name == "Jane Doe"

    @pytest.mark.asyncio
    async def test_run_sets_content_hash(self) -> None:
        """Agent sets content_hash from raw text SHA-256."""
        settings = _make_settings()
        state = _make_state()
        profile = _make_profile()

        with (
            patch("job_hunter_agents.agents.resume_parser.PDFParser") as mock_pdf_cls,
            patch.object(
                ResumeParserAgent,
                "_call_llm",
                new_callable=AsyncMock,
                return_value=profile,
            ),
            patch("job_hunter_agents.agents.base.AsyncAnthropic"),
            patch("job_hunter_agents.agents.base.instructor"),
        ):
            mock_pdf = mock_pdf_cls.return_value
            mock_pdf.extract_text = AsyncMock(return_value="text")

            agent = ResumeParserAgent(settings)
            result = await agent.run(state)

        assert result.profile is not None
        assert len(result.profile.content_hash) == 64
