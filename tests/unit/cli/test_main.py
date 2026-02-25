"""Tests for CLI entrypoint."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from job_hunter_cli.main import app
from job_hunter_core.models.run import RunResult

runner = CliRunner()


def _make_run_result(status: str = "success") -> RunResult:
    """Create a minimal RunResult for CLI testing."""
    return RunResult(
        run_id="test-run",
        status=status,
        companies_attempted=5,
        companies_succeeded=4,
        jobs_scraped=20,
        jobs_scored=15,
        jobs_in_output=10,
        output_files=[],
        email_sent=False,
        errors=[],
        total_tokens_used=1000,
        estimated_cost_usd=0.05,
        duration_seconds=3.2,
        completed_at=datetime.now(UTC),
    )


@pytest.mark.unit
class TestRunCommand:
    """Test the 'run' CLI command."""

    def test_run_requires_prefs(self, tmp_path: Path) -> None:
        """Missing --prefs exits with code 1."""
        resume = tmp_path / "resume.pdf"
        resume.write_text("fake pdf")

        result = runner.invoke(app, ["run", str(resume)])
        assert result.exit_code != 0

    def test_run_success_prints_summary(self, tmp_path: Path) -> None:
        """Mocked pipeline produces success output."""
        resume = tmp_path / "resume.pdf"
        resume.write_text("fake pdf")
        mock_result = _make_run_result(status="success")

        with (
            patch("job_hunter_cli.main.Settings") as mock_settings_cls,
            patch("job_hunter_cli.main.Pipeline") as mock_pipeline_cls,
            patch("job_hunter_cli.main.configure_logging"),
            patch("job_hunter_cli.main.configure_tracing"),
        ):
            mock_settings_cls.return_value = MagicMock()
            mock_pipeline = MagicMock()
            mock_pipeline.run = MagicMock(return_value=mock_result)
            mock_pipeline_cls.return_value = mock_pipeline

            with patch("job_hunter_cli.main.asyncio") as mock_asyncio:
                mock_asyncio.run.return_value = mock_result

                result = runner.invoke(
                    app, ["run", str(resume), "--prefs", "Remote Python roles"]
                )

        assert result.exit_code == 0
        assert "success" in result.output

    def test_run_lite_sets_sqlite(self, tmp_path: Path) -> None:
        """--lite flag sets db_backend to sqlite."""
        resume = tmp_path / "resume.pdf"
        resume.write_text("fake pdf")
        mock_result = _make_run_result()

        with (
            patch("job_hunter_cli.main.Settings") as mock_settings_cls,
            patch("job_hunter_cli.main.Pipeline"),
            patch("job_hunter_cli.main.configure_logging"),
            patch("job_hunter_cli.main.configure_tracing"),
            patch("job_hunter_cli.main.asyncio") as mock_asyncio,
        ):
            mock_settings = MagicMock()
            mock_settings_cls.return_value = mock_settings
            mock_asyncio.run.return_value = mock_result

            runner.invoke(
                app,
                ["run", str(resume), "--prefs", "test", "--lite"],
            )

        assert mock_settings.db_backend == "sqlite"
        assert mock_settings.embedding_provider == "local"
        assert mock_settings.cache_backend == "db"

    def test_run_verbose_sets_debug(self, tmp_path: Path) -> None:
        """--verbose flag sets log_level to DEBUG."""
        resume = tmp_path / "resume.pdf"
        resume.write_text("fake pdf")
        mock_result = _make_run_result()

        with (
            patch("job_hunter_cli.main.Settings") as mock_settings_cls,
            patch("job_hunter_cli.main.Pipeline"),
            patch("job_hunter_cli.main.configure_logging"),
            patch("job_hunter_cli.main.configure_tracing"),
            patch("job_hunter_cli.main.asyncio") as mock_asyncio,
        ):
            mock_settings = MagicMock()
            mock_settings_cls.return_value = mock_settings
            mock_asyncio.run.return_value = mock_result

            runner.invoke(
                app,
                ["run", str(resume), "--prefs", "test", "--verbose"],
            )

        assert mock_settings.log_level == "DEBUG"

    def test_run_failed_exits_nonzero(self, tmp_path: Path) -> None:
        """Pipeline returning status=failed results in exit code 1."""
        resume = tmp_path / "resume.pdf"
        resume.write_text("fake pdf")
        mock_result = _make_run_result(status="failed")

        with (
            patch("job_hunter_cli.main.Settings") as mock_settings_cls,
            patch("job_hunter_cli.main.Pipeline"),
            patch("job_hunter_cli.main.configure_logging"),
            patch("job_hunter_cli.main.configure_tracing"),
            patch("job_hunter_cli.main.asyncio") as mock_asyncio,
        ):
            mock_settings_cls.return_value = MagicMock()
            mock_asyncio.run.return_value = mock_result

            result = runner.invoke(
                app, ["run", str(resume), "--prefs", "test"]
            )

        assert result.exit_code == 1


@pytest.mark.unit
class TestVersionCommand:
    """Test the 'version' CLI command."""

    def test_version_shows_version(self) -> None:
        """Prints version string."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "v0.1.0" in result.output
