"""Integration tests for Temporal orchestration.

Requires a running Temporal dev server: `make dev-temporal`.
Tests use dry-run patches so no real LLM/search/scraping calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.integration.conftest import skip_no_temporal

pytestmark = [pytest.mark.integration, skip_no_temporal]


def _make_test_settings() -> MagicMock:
    """Create settings pointing to local Temporal."""
    from tests.mocks.mock_settings import make_settings

    return make_settings(
        orchestrator="temporal",
        temporal_address="localhost:7233",
        temporal_namespace="default",
        temporal_task_queue="test-default",
        temporal_llm_task_queue="test-llm",
        temporal_scraping_task_queue="test-scraping",
        temporal_workflow_timeout_seconds=120,
    )


@pytest.mark.asyncio
async def test_temporal_client_connects() -> None:
    """Verify we can connect to local Temporal dev server."""
    from temporalio.client import Client

    client = await Client.connect("localhost:7233")
    assert client is not None


@pytest.mark.asyncio
async def test_temporal_orchestrator_fallback_when_unavailable() -> None:
    """TemporalOrchestrator falls back to Pipeline when server is down."""
    from unittest.mock import AsyncMock, patch

    from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator
    from job_hunter_core.models.run import RunResult
    from tests.mocks.mock_factories import make_run_config

    settings = _make_test_settings()
    settings.temporal_address = "localhost:19999"  # unreachable port

    fallback_result = RunResult(
        run_id="test",
        status="success",
        companies_attempted=0,
        companies_succeeded=0,
        jobs_scraped=0,
        jobs_scored=0,
        jobs_in_output=0,
        output_files=[],
        email_sent=False,
        errors=[],
        total_tokens_used=0,
        estimated_cost_usd=0.0,
        duration_seconds=0.1,
    )

    mock_pipeline = AsyncMock()
    mock_pipeline.run = AsyncMock(return_value=fallback_result)

    with patch(
        "job_hunter_agents.orchestrator.temporal_orchestrator.Pipeline",
        return_value=mock_pipeline,
    ):
        orchestrator = TemporalOrchestrator(settings)
        config = make_run_config()
        result = await orchestrator.run(config)
        assert result.status == "success"
        mock_pipeline.run.assert_awaited_once()
