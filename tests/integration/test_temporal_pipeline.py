"""Integration tests for Temporal orchestration.

Two groups:
- Tests that require a running Temporal dev server (`make dev-temporal`)
- Tests that exercise the fallback path (no Temporal needed)
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.integration.conftest import skip_no_temporal

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


def _make_temporal_settings() -> MagicMock:
    """Create settings pointing to local Temporal."""
    from tests.mocks.mock_settings import make_settings

    return make_settings(
        orchestrator="temporal",
        temporal_address="localhost:7233",
        temporal_namespace="default",
        temporal_task_queue="test-default",
        temporal_llm_task_queue="test-llm",
        temporal_scraping_task_queue="test-scraping",
        temporal_tls_cert_path=None,
        temporal_tls_key_path=None,
        temporal_api_key=None,
        temporal_workflow_timeout_seconds=120,
    )


# ---------------------------------------------------------------------------
# Tests requiring a running Temporal server
# ---------------------------------------------------------------------------


@skip_no_temporal
async def test_temporal_client_connects() -> None:
    """Verify we can connect to local Temporal dev server."""
    from temporalio.client import Client

    client = await Client.connect("localhost:7233")
    assert client is not None


# ---------------------------------------------------------------------------
# Fallback tests — no Temporal server needed
# ---------------------------------------------------------------------------


async def test_temporal_orchestrator_fallback_when_unavailable() -> None:
    """TemporalOrchestrator falls back to Pipeline when server is down."""
    from unittest.mock import AsyncMock, patch

    from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator
    from job_hunter_core.models.run import RunResult
    from tests.mocks.mock_factories import make_run_config

    settings = _make_temporal_settings()
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
        "job_hunter_agents.orchestrator.pipeline.Pipeline",
        return_value=mock_pipeline,
    ):
        orchestrator = TemporalOrchestrator(settings)
        config = make_run_config()
        result = await orchestrator.run(config)
        assert result.status == "success"
        mock_pipeline.run.assert_awaited_once()


async def test_temporal_fallback_runs_full_dryrun_pipeline(
    dry_run_patches: ExitStack, tmp_path: Path
) -> None:
    """TemporalOrchestrator fallback runs the real checkpoint pipeline with dry-run patches."""
    from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator
    from job_hunter_core.models.run import RunConfig
    from tests.mocks.mock_settings import make_settings

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()

    settings = make_settings(
        orchestrator="temporal",
        temporal_address="localhost:19999",  # unreachable → triggers fallback
        temporal_namespace="default",
        temporal_task_queue="test-default",
        temporal_llm_task_queue="test-llm",
        temporal_scraping_task_queue="test-scraping",
        temporal_tls_cert_path=None,
        temporal_tls_key_path=None,
        temporal_api_key=None,
        temporal_workflow_timeout_seconds=120,
        output_dir=output_dir,
        checkpoint_dir=checkpoint_dir,
        checkpoint_enabled=True,
        min_score_threshold=0,
        max_concurrent_scrapers=2,
    )

    config = RunConfig(
        resume_path=Path(__file__).parent.parent / "fixtures" / "sample_resume.pdf",
        preferences_text="Python remote roles at startups",
        dry_run=True,
        company_limit=1,
    )

    orchestrator = TemporalOrchestrator(settings)
    result = await orchestrator.run(config)

    assert result.status in ("success", "partial")
    assert result.jobs_scored > 0
    assert result.total_tokens_used > 0
    assert result.estimated_cost_usd > 0


def test_cli_temporal_flag_with_fallback() -> None:
    """CLI --temporal flag falls back to checkpoint pipeline when Temporal is down."""
    from typer.testing import CliRunner

    from job_hunter_cli.main import app

    runner = CliRunner()
    fixture_resume = Path(__file__).parent.parent / "fixtures" / "sample_resume.pdf"

    result = runner.invoke(
        app,
        [
            "run",
            str(fixture_resume),
            "--prefs",
            "Python remote roles at startups",
            "--dry-run",
            "--lite",
            "--company-limit",
            "1",
            "--temporal",
        ],
        env={
            "JH_ANTHROPIC_API_KEY": "fake-key",
            "JH_TAVILY_API_KEY": "fake-key",
        },
    )
    assert result.exit_code == 0, (
        f"CLI --temporal failed with code {result.exit_code}: {result.output}"
    )
    assert "Orchestrator: Temporal" in result.output
    assert "Run complete:" in result.output
