"""Integration tests for Temporal orchestration.

Three groups:
- Tests that require a running Temporal dev server (`make dev-temporal`)
- Tests that verify error behavior when Temporal is unavailable
- Tests for checkpoint pipeline (Temporal disabled)
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.integration.conftest import skip_no_temporal

pytestmark = pytest.mark.integration

FIXTURE_RESUME = Path(__file__).parent.parent / "fixtures" / "sample_resume.pdf"


def _make_temporal_settings(**overrides: object) -> MagicMock:
    """Create settings pointing to local Temporal."""
    from tests.mocks.mock_settings import make_settings

    defaults = {
        "orchestrator": "temporal",
        "temporal_address": "localhost:7233",
        "temporal_namespace": "default",
        "temporal_task_queue": "test-default",
        "temporal_llm_task_queue": "test-llm",
        "temporal_scraping_task_queue": "test-scraping",
        "temporal_tls_cert_path": None,
        "temporal_tls_key_path": None,
        "temporal_api_key": None,
        "temporal_workflow_timeout_seconds": 120,
    }
    defaults.update(overrides)
    return make_settings(**defaults)


# ---------------------------------------------------------------------------
# Tests requiring a running Temporal server
# ---------------------------------------------------------------------------


@skip_no_temporal
async def test_temporal_client_connects() -> None:
    """Verify we can connect to local Temporal dev server."""
    from temporalio.client import Client

    client = await Client.connect("localhost:7233")
    assert client is not None


@skip_no_temporal
async def test_temporal_dryrun_full_pipeline(dry_run_patches: ExitStack, tmp_path: Path) -> None:
    """Full pipeline via Temporal with dry-run patches — exercises real Temporal server."""
    from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator
    from job_hunter_core.models.run import RunConfig

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()

    settings = _make_temporal_settings(
        output_dir=output_dir,
        checkpoint_dir=checkpoint_dir,
        checkpoint_enabled=True,
        min_score_threshold=0,
        max_concurrent_scrapers=2,
    )

    config = RunConfig(
        resume_path=FIXTURE_RESUME,
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


@skip_no_temporal
async def test_temporal_dryrun_produces_output_files(
    dry_run_patches: ExitStack, tmp_path: Path
) -> None:
    """Temporal pipeline with dry-run produces CSV and XLSX output files."""
    from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator
    from job_hunter_core.models.run import RunConfig

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()

    settings = _make_temporal_settings(
        output_dir=output_dir,
        checkpoint_dir=checkpoint_dir,
        checkpoint_enabled=True,
        min_score_threshold=0,
        max_concurrent_scrapers=2,
    )

    config = RunConfig(
        resume_path=FIXTURE_RESUME,
        preferences_text="Python remote roles at startups",
        dry_run=True,
        company_limit=1,
        output_formats=["csv", "xlsx"],
    )

    orchestrator = TemporalOrchestrator(settings)
    result = await orchestrator.run(config)

    assert result.status in ("success", "partial")
    output_files = [str(f) for f in result.output_files]
    csv_files = [f for f in output_files if f.endswith(".csv")]
    xlsx_files = [f for f in output_files if f.endswith(".xlsx")]
    assert len(csv_files) >= 1, f"Expected CSV file, got: {output_files}"
    assert len(xlsx_files) >= 1, f"Expected XLSX file, got: {output_files}"


# ---------------------------------------------------------------------------
# Tests for error behavior when Temporal is unavailable
# ---------------------------------------------------------------------------


async def test_temporal_raises_when_server_unavailable() -> None:
    """TemporalOrchestrator raises TemporalConnectionError when server is down."""
    from job_hunter_agents.orchestrator.temporal_orchestrator import TemporalOrchestrator
    from job_hunter_core.exceptions import TemporalConnectionError
    from tests.mocks.mock_factories import make_run_config

    settings = _make_temporal_settings(temporal_address="localhost:19999")

    orchestrator = TemporalOrchestrator(settings)
    config = make_run_config()
    with pytest.raises(TemporalConnectionError):
        await orchestrator.run(config)


def test_cli_temporal_flag_errors_without_server() -> None:
    """CLI --temporal shows error and exits 1 when Temporal is unreachable."""
    from typer.testing import CliRunner

    from job_hunter_cli.main import app

    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            str(FIXTURE_RESUME),
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
    assert result.exit_code == 1, f"Expected exit code 1, got {result.exit_code}: {result.output}"
    assert "Orchestrator: Temporal" in result.output
    assert "Temporal server unreachable" in result.output


@skip_no_temporal
def test_cli_temporal_flag_succeeds_with_server() -> None:
    """CLI --temporal runs successfully when Temporal server is available."""
    from typer.testing import CliRunner

    from job_hunter_cli.main import app

    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            str(FIXTURE_RESUME),
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


# ---------------------------------------------------------------------------
# Checkpoint pipeline tests (Temporal disabled — the default)
# ---------------------------------------------------------------------------


async def test_checkpoint_pipeline_is_default(dry_run_patches: ExitStack, tmp_path: Path) -> None:
    """When orchestrator is 'checkpoint' (default), Pipeline uses JSON checkpoints."""
    from job_hunter_agents.orchestrator.checkpoint import load_latest_checkpoint
    from job_hunter_agents.orchestrator.pipeline import Pipeline
    from job_hunter_core.models.run import RunConfig

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()

    from tests.mocks.mock_settings import make_settings

    settings = make_settings(
        orchestrator="checkpoint",
        output_dir=output_dir,
        checkpoint_dir=checkpoint_dir,
        checkpoint_enabled=True,
        min_score_threshold=0,
        max_concurrent_scrapers=2,
    )

    config = RunConfig(
        run_id="checkpoint-default-test",
        resume_path=FIXTURE_RESUME,
        preferences_text="Python remote roles at startups",
        dry_run=True,
        company_limit=1,
    )

    pipeline = Pipeline(settings)
    result = await pipeline.run(config)

    assert result.status in ("success", "partial")
    assert result.jobs_scored > 0

    # Verify JSON checkpoint files were created
    checkpoint_files = list(checkpoint_dir.glob("checkpoint-default-test--*.json"))
    assert len(checkpoint_files) > 0, "No checkpoint files found — checkpoint mode broken"

    # Verify checkpoint can be loaded
    checkpoint = load_latest_checkpoint("checkpoint-default-test", checkpoint_dir)
    assert checkpoint is not None
    assert checkpoint.run_id == "checkpoint-default-test"


def test_cli_defaults_to_checkpoint_mode() -> None:
    """CLI without --temporal uses checkpoint orchestrator."""
    from typer.testing import CliRunner

    from job_hunter_cli.main import app

    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "run",
            str(FIXTURE_RESUME),
            "--prefs",
            "Python remote roles at startups",
            "--dry-run",
            "--lite",
            "--company-limit",
            "1",
        ],
        env={
            "JH_ANTHROPIC_API_KEY": "fake-key",
            "JH_TAVILY_API_KEY": "fake-key",
        },
    )
    assert result.exit_code in (0, 1), f"CLI failed with code {result.exit_code}: {result.output}"
    assert "Orchestrator: checkpoint" in result.output
    assert "Run complete:" in result.output
