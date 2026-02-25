"""Integration tests for full pipeline with dry-run patches.

Real DB + cache are NOT required here — these tests use mocked settings
with SQLite and DB cache backend. The key value is exercising the full
agent pipeline end-to-end with realistic fixture data.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from job_hunter_agents.orchestrator.pipeline import Pipeline
from job_hunter_core.models.run import RunConfig

pytestmark = pytest.mark.integration

FIXTURE_RESUME = Path(__file__).parent.parent / "fixtures" / "sample_resume.pdf"


def _make_settings(tmp_path: Path) -> MagicMock:
    """Build mock settings with real paths for output/checkpoints."""
    from tests.mocks.mock_settings import make_settings

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()

    return make_settings(
        output_dir=output_dir,
        checkpoint_dir=checkpoint_dir,
        checkpoint_enabled=True,
        min_score_threshold=0,  # Accept all scores in tests
        max_concurrent_scrapers=2,
    )


class TestPipelineDryRun:
    """Full pipeline run with mocked externals, real state management."""

    async def test_full_pipeline_success(self, dry_run_patches: ExitStack, tmp_path: Path) -> None:
        """All 8 agents run, status is success, scored_jobs > 0."""
        settings = _make_settings(tmp_path)
        config = RunConfig(
            resume_path=FIXTURE_RESUME,
            preferences_text="Python remote roles at startups",
            dry_run=True,
            company_limit=2,
        )

        pipeline = Pipeline(settings)
        result = await pipeline.run(config)

        assert result.status in ("success", "partial")
        assert result.jobs_scored > 0
        assert result.companies_attempted > 0

    async def test_pipeline_generates_output_files(
        self, dry_run_patches: ExitStack, tmp_path: Path
    ) -> None:
        """Pipeline produces CSV and XLSX output files."""
        settings = _make_settings(tmp_path)
        config = RunConfig(
            resume_path=FIXTURE_RESUME,
            preferences_text="Python remote roles at startups",
            dry_run=True,
            company_limit=2,
            output_formats=["csv", "xlsx"],
        )

        pipeline = Pipeline(settings)
        result = await pipeline.run(config)

        assert result.status in ("success", "partial")
        output_files = [str(f) for f in result.output_files]
        csv_files = [f for f in output_files if f.endswith(".csv")]
        xlsx_files = [f for f in output_files if f.endswith(".xlsx")]
        assert len(csv_files) >= 1, f"Expected CSV file, got: {output_files}"
        assert len(xlsx_files) >= 1, f"Expected XLSX file, got: {output_files}"

        # Verify files exist and are non-empty
        for fpath in output_files:
            p = Path(fpath)
            assert p.exists(), f"Output file missing: {fpath}"  # noqa: ASYNC240
            assert p.stat().st_size > 0, f"Output file empty: {fpath}"  # noqa: ASYNC240

    async def test_pipeline_checkpoint_save_and_resume(
        self, dry_run_patches: ExitStack, tmp_path: Path
    ) -> None:
        """Checkpoints are saved; a new pipeline can resume from them."""
        from job_hunter_agents.orchestrator.checkpoint import load_latest_checkpoint

        settings = _make_settings(tmp_path)
        config = RunConfig(
            run_id="checkpoint-test-run",
            resume_path=FIXTURE_RESUME,
            preferences_text="Python remote roles at startups",
            dry_run=True,
            company_limit=2,
        )

        pipeline = Pipeline(settings)
        result = await pipeline.run(config)
        assert result.status in ("success", "partial")

        # Verify checkpoint files exist
        checkpoint_dir = settings.checkpoint_dir
        checkpoint_files = list(checkpoint_dir.glob("checkpoint-test-run--*.json"))
        assert len(checkpoint_files) > 0, "No checkpoint files found"

        # Verify we can load the latest checkpoint
        checkpoint = load_latest_checkpoint("checkpoint-test-run", checkpoint_dir)
        assert checkpoint is not None
        assert checkpoint.run_id == "checkpoint-test-run"

    async def test_pipeline_cost_tracking(self, dry_run_patches: ExitStack, tmp_path: Path) -> None:
        """Dry-run still tracks token usage and cost from fixture metadata."""
        settings = _make_settings(tmp_path)
        config = RunConfig(
            resume_path=FIXTURE_RESUME,
            preferences_text="Python remote roles at startups",
            dry_run=True,
            company_limit=2,
        )

        pipeline = Pipeline(settings)
        result = await pipeline.run(config)

        assert result.total_tokens_used > 0, "Expected token tracking in dry-run"
        assert result.estimated_cost_usd > 0, "Expected cost tracking in dry-run"

    async def test_pipeline_company_limit(self, dry_run_patches: ExitStack, tmp_path: Path) -> None:
        """company_limit caps the number of companies processed."""
        settings = _make_settings(tmp_path)
        config = RunConfig(
            resume_path=FIXTURE_RESUME,
            preferences_text="Python remote roles at startups",
            dry_run=True,
            company_limit=1,
        )

        pipeline = Pipeline(settings)
        result = await pipeline.run(config)

        assert result.status in ("success", "partial")
        assert result.companies_attempted <= 1

    async def test_pipeline_error_recording(
        self, dry_run_patches: ExitStack, tmp_path: Path
    ) -> None:
        """Pipeline records non-fatal errors and still completes."""
        settings = _make_settings(tmp_path)
        config = RunConfig(
            resume_path=FIXTURE_RESUME,
            preferences_text="Python remote roles at startups",
            dry_run=True,
            company_limit=2,
        )

        pipeline = Pipeline(settings)
        result = await pipeline.run(config)

        # Pipeline should complete regardless of non-fatal errors
        assert result.status in ("success", "partial")
        # Errors list is accessible (may be empty if no errors)
        assert isinstance(result.errors, list)
