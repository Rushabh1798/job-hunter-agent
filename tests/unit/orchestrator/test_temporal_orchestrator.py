"""Unit tests for Temporal orchestrator."""

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
    mock_settings.temporal_embedded_worker = False
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
async def test_run_raises_on_connection_error(temporal_settings: MagicMock) -> None:
    """Raises TemporalConnectionError when Temporal is unreachable (no fallback)."""
    with patch(
        "job_hunter_agents.orchestrator.temporal_orchestrator.create_temporal_client",
        side_effect=TemporalConnectionError("refused"),
    ):
        from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator

        orchestrator = TemporalOrchestrator(temporal_settings)
        with pytest.raises(TemporalConnectionError, match="refused"):
            await orchestrator.run(_make_run_config())


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


@pytest.mark.asyncio
async def test_run_with_embedded_worker(temporal_settings: MagicMock) -> None:
    """Embedded worker mode starts workers alongside workflow execution."""
    temporal_settings.temporal_embedded_worker = True
    temporal_settings.temporal_task_queue = "test-q"
    temporal_settings.temporal_llm_task_queue = "test-q"
    temporal_settings.temporal_scraping_task_queue = "test-q"

    mock_client = AsyncMock()
    mock_client.execute_workflow = AsyncMock(return_value=_make_workflow_output())

    with (
        patch(
            "job_hunter_agents.orchestrator.temporal_orchestrator.create_temporal_client",
            return_value=mock_client,
        ),
        patch(
            "temporalio.worker.Worker",
        ) as mock_worker_cls,
        patch(
            "job_hunter_agents.orchestrator.temporal_activities.set_settings_override",
        ) as mock_set_override,
    ):
        mock_worker = AsyncMock()
        mock_worker.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_worker.__aexit__ = AsyncMock(return_value=False)
        mock_worker_cls.return_value = mock_worker

        from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator

        orchestrator = TemporalOrchestrator(temporal_settings)
        result = await orchestrator.run(_make_run_config())

        assert result.status == "success"
        # Worker was created for the single deduplicated queue
        mock_worker_cls.assert_called_once()
        # Settings override was set then cleared
        assert mock_set_override.call_count == 2
        mock_set_override.assert_any_call(temporal_settings)
        mock_set_override.assert_any_call(None)


@pytest.mark.asyncio
async def test_embedded_worker_deduplicates_queues(temporal_settings: MagicMock) -> None:
    """When all queues are the same, only one worker is created."""
    temporal_settings.temporal_embedded_worker = True
    temporal_settings.temporal_task_queue = "same-q"
    temporal_settings.temporal_llm_task_queue = "same-q"
    temporal_settings.temporal_scraping_task_queue = "same-q"

    mock_client = AsyncMock()
    mock_client.execute_workflow = AsyncMock(return_value=_make_workflow_output())

    with (
        patch(
            "job_hunter_agents.orchestrator.temporal_orchestrator.create_temporal_client",
            return_value=mock_client,
        ),
        patch(
            "temporalio.worker.Worker",
        ) as mock_worker_cls,
        patch(
            "job_hunter_agents.orchestrator.temporal_activities.set_settings_override",
        ),
    ):
        mock_worker = AsyncMock()
        mock_worker.__aenter__ = AsyncMock(return_value=mock_worker)
        mock_worker.__aexit__ = AsyncMock(return_value=False)
        mock_worker_cls.return_value = mock_worker

        from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator

        orchestrator = TemporalOrchestrator(temporal_settings)
        await orchestrator.run(_make_run_config())

        # Only 1 worker for the single unique queue
        assert mock_worker_cls.call_count == 1


@pytest.mark.asyncio
async def test_to_run_result_handles_non_dict_errors() -> None:
    """Non-dict errors from Temporal deserialization are logged and skipped."""
    from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator

    # Simulate Temporal returning bad data by constructing output then mutating
    output = WorkflowOutput(
        status="partial",
        errors=[
            {"agent_name": "scraper", "error_type": "TimeoutError", "error_message": "timeout"},
        ],
    )
    # Simulate Temporal deserialization bug: non-dict entries sneak in
    output.errors.extend(["string_error", 42])  # type: ignore[list-item]

    result = TemporalOrchestrator._to_run_result(output, "test_run")

    # Only the valid dict error is included; non-dicts are logged and skipped
    assert len(result.errors) == 1
    assert result.errors[0].agent_name == "scraper"


@pytest.mark.asyncio
async def test_to_run_result_empty_errors() -> None:
    """Empty errors list converts cleanly."""
    from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator

    output = WorkflowOutput(status="success", errors=[])
    result = TemporalOrchestrator._to_run_result(output, "test_run")

    assert result.errors == []
    assert result.status == "success"
