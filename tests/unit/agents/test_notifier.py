"""Tests for notifier agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from job_hunter_agents.agents.notifier import NotifierAgent
from job_hunter_core.models.candidate import CandidateProfile, Skill
from job_hunter_core.models.run import RunConfig, RunResult
from job_hunter_core.state import PipelineState
from tests.mocks.mock_settings import make_settings


def _make_state() -> PipelineState:
    """Create state with profile and run result."""
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
    state.run_result = RunResult(
        run_id="test_run",
        status="success",
        companies_attempted=5,
        companies_succeeded=4,
        jobs_scraped=20,
        jobs_scored=10,
        jobs_in_output=10,
        output_files=[Path("/tmp/results.xlsx")],
        email_sent=False,
        errors=[],
        total_tokens_used=1000,
        estimated_cost_usd=0.5,
        duration_seconds=30.0,
    )
    return state


@pytest.mark.unit
class TestNotifierAgent:
    """Test NotifierAgent."""

    @pytest.mark.asyncio
    async def test_dry_run_skips_email(self) -> None:
        """Dry run mode skips email sending."""
        settings = make_settings(
            email_provider="smtp",
            smtp_host="smtp.test.com",
            smtp_port=587,
        )
        state = _make_state()
        state.config.dry_run = True

        agent = NotifierAgent(settings)
        result = await agent.run(state)

        assert result.run_result is not None
        assert result.run_result.email_sent is False

    @pytest.mark.asyncio
    async def test_sends_email(self) -> None:
        """Agent sends email via EmailSender."""
        settings = make_settings(
            email_provider="smtp",
            smtp_host="smtp.test.com",
            smtp_port=587,
        )
        state = _make_state()

        with patch("job_hunter_agents.agents.notifier.EmailSender") as mock_sender_cls:
            mock_sender = mock_sender_cls.return_value
            mock_sender.send = AsyncMock(return_value=True)

            agent = NotifierAgent(settings)
            result = await agent.run(state)

        assert result.run_result is not None
        assert result.run_result.email_sent is True
        mock_sender.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_email_failure_recorded(self) -> None:
        """Email failure is recorded but doesn't crash pipeline."""
        settings = make_settings(
            email_provider="smtp",
            smtp_host="smtp.test.com",
            smtp_port=587,
        )
        state = _make_state()

        with patch("job_hunter_agents.agents.notifier.EmailSender") as mock_sender_cls:
            mock_sender = mock_sender_cls.return_value
            mock_sender.send = AsyncMock(side_effect=RuntimeError("SMTP error"))

            agent = NotifierAgent(settings)
            result = await agent.run(state)

        assert len(result.errors) >= 1
