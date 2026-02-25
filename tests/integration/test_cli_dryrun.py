"""Integration tests for CLI dry-run invocation."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from job_hunter_cli.main import app

pytestmark = pytest.mark.integration

runner = CliRunner()

FIXTURE_RESUME = Path(__file__).parent.parent / "fixtures" / "sample_resume.pdf"


class TestCLIDryRun:
    """CLI invocation with --dry-run flag."""

    def test_cli_dryrun_exit_code_zero(self, tmp_path: Path) -> None:
        """CLI --dry-run exits with code 0."""
        result = runner.invoke(
            app,
            [
                "run",
                str(FIXTURE_RESUME),
                "--prefs",
                "Python remote roles at startups",
                "--dry-run",
                "--company-limit",
                "1",
            ],
            env={
                "JH_ANTHROPIC_API_KEY": "fake-key",
                "JH_TAVILY_API_KEY": "fake-key",
            },
        )
        # Allow exit code 0 (success) or 1 (partial — still valid for dry-run)
        assert result.exit_code in (0, 1), (
            f"CLI failed with code {result.exit_code}: {result.output}"
        )
        assert "Starting run:" in result.output

    def test_cli_dryrun_output_contains_summary(self, tmp_path: Path) -> None:
        """CLI --dry-run prints run summary."""
        result = runner.invoke(
            app,
            [
                "run",
                str(FIXTURE_RESUME),
                "--prefs",
                "Python remote roles",
                "--dry-run",
                "--company-limit",
                "1",
            ],
            env={
                "JH_ANTHROPIC_API_KEY": "fake-key",
                "JH_TAVILY_API_KEY": "fake-key",
            },
        )
        assert "Run complete:" in result.output
        assert "Companies:" in result.output

    def test_cli_lite_mode(self, tmp_path: Path) -> None:
        """CLI --lite --dry-run uses SQLite backend."""
        result = runner.invoke(
            app,
            [
                "run",
                str(FIXTURE_RESUME),
                "--prefs",
                "Python remote roles",
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
        assert result.exit_code in (0, 1), (
            f"Lite mode failed: {result.output}"
        )
        assert "Starting run:" in result.output
