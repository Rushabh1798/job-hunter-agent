"""Unit tests for Temporal orchestrator with fallback logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from job_hunter_agents.orchestrator.temporal_payloads import WorkflowOutput
from job_hunter_core.exceptions import TemporalConnectionError
from job_hunter_core.models.run import RunConfig, RunResult

pytestmark = pytest.mark.unit


@pytest.fixture
def temporal_settings(mock_settings: MagicMock) -> MagicMock:
    """Settings configured for Temporal."""
    mock_settings.orchestrator = "temporal"
    mock_settings.temporal_address = "localhost:7233"
    mock_settings.temporal_namespace = "default"
    mock_settings.temporal_task_queue = "job-hunter-default"
    mock_settings.temporal_llm_task_queue = "job-hunter-llm"
    mock_settings.temporal_scraping_task_queue = "job-hunter-scraping"
    mock_settings.temporal_tls_cert_path = None
    mock_settings.temporal_tls_key_path = None
    mock_settings.temporal_api_key = None
    mock_settings.temporal_workflow_timeout_seconds = 1800
    return mock_settings


def _make_run_config() -> RunConfig:
    """Create a mock RunConfig."""
    from tests.mocks.mock_factories import make_run_config

    return make_run_config()


def _make_workflow_output() -> WorkflowOutput:
    """Create a WorkflowOutput for testing."""
    return WorkflowOutput(
        status="success",
        companies_attempted=5,
        companies_succeeded=4,
        jobs_scraped=20,
        jobs_scored=15,
        jobs_in_output=15,
        output_files=["/output/results.csv"],
        email_sent=True,
        total_tokens_used=1000,
        estimated_cost_usd=0.50,
        duration_seconds=30.0,
        errors=[],
    )


@pytest.mark.asyncio
async def test_run_success_via_temporal(temporal_settings: MagicMock) -> None:
    """Workflow executes successfully via Temporal."""
    mock_client = AsyncMock()
    mock_client.execute_workflow = AsyncMock(return_value=_make_workflow_output())

    with patch(
        "job_hunter_agents.orchestrator.temporal_orchestrator.create_temporal_client",
        return_value=mock_client,
    ):
        from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator

        orchestrator = TemporalOrchestrator(temporal_settings)
        config = _make_run_config()
        result = await orchestrator.run(config)

        assert isinstance(result, RunResult)
        assert result.status == "success"
        assert result.jobs_scored == 15
        assert result.estimated_cost_usd == 0.50
        mock_client.execute_workflow.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_falls_back_on_connection_error(temporal_settings: MagicMock) -> None:
    """Falls back to checkpoint Pipeline when Temporal is unreachable."""
    fallback_result = RunResult(
        run_id="test",
        status="success",
        companies_attempted=1,
        companies_succeeded=1,
        jobs_scraped=5,
        jobs_scored=3,
        jobs_in_output=3,
        output_files=[],
        email_sent=False,
        errors=[],
        total_tokens_used=100,
        estimated_cost_usd=0.01,
        duration_seconds=5.0,
    )

    mock_pipeline = AsyncMock()
    mock_pipeline.run = AsyncMock(return_value=fallback_result)

    with (
        patch(
            "job_hunter_agents.orchestrator.temporal_orchestrator.create_temporal_client",
            side_effect=TemporalConnectionError("refused"),
        ),
        patch(
            "job_hunter_agents.orchestrator.pipeline.Pipeline",
            return_value=mock_pipeline,
        ),
    ):
        from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator

        orchestrator = TemporalOrchestrator(temporal_settings)
        result = await orchestrator.run(_make_run_config())

        assert result.status == "success"
        assert result.jobs_scraped == 5
        mock_pipeline.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_input_maps_config_fields(temporal_settings: MagicMock) -> None:
    """WorkflowInput is correctly built from RunConfig + Settings."""
    from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator

    orchestrator = TemporalOrchestrator(temporal_settings)
    config = _make_run_config()
    workflow_input = orchestrator._build_input(config)

    assert workflow_input.run_id == config.run_id
    assert workflow_input.resume_path == str(config.resume_path)
    assert workflow_input.default_queue == "job-hunter-default"
    assert workflow_input.llm_queue == "job-hunter-llm"
    assert workflow_input.scraping_queue == "job-hunter-scraping"


@pytest.mark.asyncio
async def test_to_run_result_converts_output(temporal_settings: MagicMock) -> None:
    """WorkflowOutput is correctly converted to RunResult."""
    from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator

    output = _make_workflow_output()
    result = TemporalOrchestrator._to_run_result(output, "run_test")

    assert result.run_id == "run_test"
    assert result.status == "success"
    assert result.output_files == [Path("/output/results.csv")]
    assert result.email_sent is True
    assert result.estimated_cost_usd == 0.50
