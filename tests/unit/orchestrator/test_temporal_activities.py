"""Unit tests for Temporal activities — mock the agent layer."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from job_hunter_agents.orchestrator.temporal_payloads import (
    ScrapeCompanyInput,
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

    async def close(self) -> None:
        """No-op cleanup."""


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


@pytest.mark.asyncio
async def test_scrape_company_activity() -> None:
    """scrape_company_activity runs JobsScraperAgent for a single company."""
    from tests.mocks.mock_factories import make_company, make_run_config

    company = make_company()
    config = make_run_config()
    company_data = json.loads(company.model_dump_json())
    config_data = json.loads(config.model_dump_json())
    payload = ScrapeCompanyInput(company_data=company_data, config_data=config_data)

    class _MockScraperAgent:
        def __init__(self, settings: object) -> None:
            pass

        async def run(self, state: object) -> object:
            from tests.mocks.mock_factories import make_raw_job

            raw = make_raw_job(company_id=state.companies[0].id)  # type: ignore[attr-defined]
            state.raw_jobs = [raw]  # type: ignore[attr-defined]
            return state

        async def close(self) -> None:
            pass

    with (
        patch(
            "job_hunter_agents.orchestrator.temporal_activities._get_settings",
            return_value=MagicMock(),
        ),
        patch(
            "job_hunter_agents.agents.jobs_scraper.JobsScraperAgent",
            _MockScraperAgent,
        ),
    ):
        from job_hunter_agents.orchestrator.temporal_activities import (
            scrape_company_activity,
        )

        result = await scrape_company_activity(payload)

    assert len(result.raw_jobs) == 1
    assert "company_id" in result.raw_jobs[0]
    assert result.errors == []


@pytest.mark.asyncio
async def test_settings_override_used_when_set() -> None:
    """_get_settings returns the override when set."""
    from job_hunter_agents.orchestrator.temporal_activities import (
        _get_settings,
        set_settings_override,
    )

    mock = MagicMock()
    mock.custom_field = "test"

    set_settings_override(mock)
    try:
        result = _get_settings()
        assert result is mock
    finally:
        set_settings_override(None)

    # After clearing, it should try to create Settings from env
    with patch(
        "job_hunter_core.config.settings.Settings",
        return_value=MagicMock(),
    ) as mock_settings_cls:
        result = _get_settings()
        assert result is not mock
        mock_settings_cls.assert_called_once()
