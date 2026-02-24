"""Tests for run domain models."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_hunter_core.models.run import AgentError, PipelineCheckpoint, RunConfig, RunResult


@pytest.mark.unit
class TestRunConfig:
    """Test RunConfig model."""

    def test_auto_generated_run_id(self) -> None:
        """RunConfig generates a run_id automatically."""
        rc = RunConfig(resume_path=Path("test.pdf"), preferences_text="ML roles")
        assert rc.run_id.startswith("run_")

    def test_defaults(self) -> None:
        """RunConfig has sensible defaults."""
        rc = RunConfig(resume_path=Path("test.pdf"), preferences_text="test")
        assert rc.dry_run is False
        assert rc.lite_mode is False
        assert rc.output_formats == ["xlsx", "csv"]

    def test_custom_run_id(self) -> None:
        """RunConfig accepts custom run_id."""
        rc = RunConfig(
            run_id="custom_123",
            resume_path=Path("test.pdf"),
            preferences_text="test",
        )
        assert rc.run_id == "custom_123"


@pytest.mark.unit
class TestAgentError:
    """Test AgentError model."""

    def test_basic_error(self) -> None:
        """AgentError records error details."""
        err = AgentError(
            agent_name="scraper",
            error_type="TimeoutError",
            error_message="Connection timed out",
        )
        assert err.is_fatal is False
        assert err.company_name is None

    def test_fatal_error(self) -> None:
        """Fatal error flag is recorded."""
        err = AgentError(
            agent_name="scorer",
            error_type="CostLimitExceededError",
            error_message="Cost exceeded $5",
            is_fatal=True,
        )
        assert err.is_fatal is True


@pytest.mark.unit
class TestPipelineCheckpoint:
    """Test PipelineCheckpoint model."""

    def test_valid_checkpoint(self) -> None:
        """Checkpoint with required fields creates successfully."""
        cp = PipelineCheckpoint(
            run_id="run_123",
            completed_step="parse_resume",
            state_snapshot={"config": {}, "profile": None},
        )
        assert cp.completed_step == "parse_resume"


@pytest.mark.unit
class TestRunResult:
    """Test RunResult model."""

    def test_successful_run(self) -> None:
        """RunResult for a successful run."""
        r = RunResult(
            run_id="run_123",
            status="success",
            companies_attempted=10,
            companies_succeeded=8,
            jobs_scraped=50,
            jobs_scored=30,
            jobs_in_output=15,
            output_files=[Path("output/results.xlsx")],
            email_sent=True,
            errors=[],
            total_tokens_used=50000,
            estimated_cost_usd=1.50,
            duration_seconds=120.5,
        )
        assert r.status == "success"
        assert r.jobs_in_output == 15
