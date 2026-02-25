"""Unit tests for Temporal activities — mock the agent layer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from job_hunter_agents.orchestrator.temporal_payloads import (
    StepInput,
)

pytestmark = pytest.mark.unit


def _make_state_snapshot(**overrides: object) -> dict[str, object]:
    """Build a minimal state snapshot for testing."""
    base: dict[str, object] = {
        "config": {
            "run_id": "test_run",
            "resume_path": "/tmp/resume.pdf",
            "preferences_text": "Python dev",
            "dry_run": False,
            "force_rescrape": False,
            "company_limit": None,
            "lite_mode": False,
            "output_formats": ["csv"],
        },
        "profile": None,
        "preferences": None,
        "companies": [],
        "raw_jobs": [],
        "normalized_jobs": [],
        "scored_jobs": [],
        "errors": [],
        "total_tokens": 0,
        "total_cost_usd": 0.0,
    }
    base.update(overrides)
    return base


class _MockAgent:
    """Mock agent that modifies state tokens."""

    def __init__(self, settings: object) -> None:
        self.settings = settings

    async def run(self, state: object) -> object:
        state.total_tokens += 100  # type: ignore[attr-defined]
        state.total_cost_usd += 0.01  # type: ignore[attr-defined]
        return state


@pytest.mark.asyncio
async def test_parse_resume_activity_calls_agent() -> None:
    """parse_resume_activity delegates to ResumeParserAgent."""
    payload = StepInput(state_snapshot=_make_state_snapshot())

    with (
        patch(
            "job_hunter_agents.orchestrator.temporal_activities._get_settings",
            return_value=MagicMock(),
        ),
        patch(
            "job_hunter_agents.orchestrator.temporal_registry.AGENT_MAP",
            {"ResumeParserAgent": _MockAgent},
        ),
    ):
        from job_hunter_agents.orchestrator.temporal_activities import (
            parse_resume_activity,
        )

        result = await parse_resume_activity(payload)
        assert result.tokens_used == 100
        assert result.cost_usd == pytest.approx(0.01)
        assert "config" in result.state_snapshot


@pytest.mark.asyncio
async def test_find_companies_activity_calls_agent() -> None:
    """find_companies_activity delegates to CompanyFinderAgent."""
    payload = StepInput(state_snapshot=_make_state_snapshot())

    with (
        patch(
            "job_hunter_agents.orchestrator.temporal_activities._get_settings",
            return_value=MagicMock(),
        ),
        patch(
            "job_hunter_agents.orchestrator.temporal_registry.AGENT_MAP",
            {"CompanyFinderAgent": _MockAgent},
        ),
    ):
        from job_hunter_agents.orchestrator.temporal_activities import (
            find_companies_activity,
        )

        result = await find_companies_activity(payload)
        assert result.tokens_used == 100


@pytest.mark.asyncio
async def test_step_result_tracks_token_delta() -> None:
    """StepResult captures token delta (not total)."""
    snapshot = _make_state_snapshot(total_tokens=500, total_cost_usd=0.05)
    payload = StepInput(state_snapshot=snapshot)

    with (
        patch(
            "job_hunter_agents.orchestrator.temporal_activities._get_settings",
            return_value=MagicMock(),
        ),
        patch(
            "job_hunter_agents.orchestrator.temporal_registry.AGENT_MAP",
            {"PrefsParserAgent": _MockAgent},
        ),
    ):
        from job_hunter_agents.orchestrator.temporal_activities import (
            parse_prefs_activity,
        )

        result = await parse_prefs_activity(payload)
        assert result.tokens_used == 100
        assert result.cost_usd == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_process_jobs_activity_calls_agent() -> None:
    """process_jobs_activity delegates to JobProcessorAgent."""
    payload = StepInput(state_snapshot=_make_state_snapshot())

    with (
        patch(
            "job_hunter_agents.orchestrator.temporal_activities._get_settings",
            return_value=MagicMock(),
        ),
        patch(
            "job_hunter_agents.orchestrator.temporal_registry.AGENT_MAP",
            {"JobProcessorAgent": _MockAgent},
        ),
    ):
        from job_hunter_agents.orchestrator.temporal_activities import (
            process_jobs_activity,
        )

        result = await process_jobs_activity(payload)
        assert result.tokens_used == 100


@pytest.mark.asyncio
async def test_score_jobs_activity_calls_agent() -> None:
    """score_jobs_activity delegates to JobsScorerAgent."""
    payload = StepInput(state_snapshot=_make_state_snapshot())

    with (
        patch(
            "job_hunter_agents.orchestrator.temporal_activities._get_settings",
            return_value=MagicMock(),
        ),
        patch(
            "job_hunter_agents.orchestrator.temporal_registry.AGENT_MAP",
            {"JobsScorerAgent": _MockAgent},
        ),
    ):
        from job_hunter_agents.orchestrator.temporal_activities import (
            score_jobs_activity,
        )

        result = await score_jobs_activity(payload)
        assert result.tokens_used == 100


@pytest.mark.asyncio
async def test_aggregate_activity_calls_agent() -> None:
    """aggregate_activity delegates to AggregatorAgent."""
    payload = StepInput(state_snapshot=_make_state_snapshot())

    with (
        patch(
            "job_hunter_agents.orchestrator.temporal_activities._get_settings",
            return_value=MagicMock(),
        ),
        patch(
            "job_hunter_agents.orchestrator.temporal_registry.AGENT_MAP",
            {"AggregatorAgent": _MockAgent},
        ),
    ):
        from job_hunter_agents.orchestrator.temporal_activities import (
            aggregate_activity,
        )

        result = await aggregate_activity(payload)
        assert result.tokens_used == 100


@pytest.mark.asyncio
async def test_notify_activity_calls_agent() -> None:
    """notify_activity delegates to NotifierAgent."""
    payload = StepInput(state_snapshot=_make_state_snapshot())

    with (
        patch(
            "job_hunter_agents.orchestrator.temporal_activities._get_settings",
            return_value=MagicMock(),
        ),
        patch(
            "job_hunter_agents.orchestrator.temporal_registry.AGENT_MAP",
            {"NotifierAgent": _MockAgent},
        ),
    ):
        from job_hunter_agents.orchestrator.temporal_activities import (
            notify_activity,
        )

        result = await notify_activity(payload)
        assert result.tokens_used == 100
