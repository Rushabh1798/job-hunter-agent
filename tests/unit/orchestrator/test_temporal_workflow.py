"""Unit tests for Temporal workflow definition."""

from __future__ import annotations

import pytest

from job_hunter_agents.orchestrator.temporal_payloads import (
    WorkflowInput,
    WorkflowOutput,
)
from job_hunter_agents.orchestrator.temporal_workflow import JobHuntWorkflow

pytestmark = pytest.mark.unit


def _make_workflow_input(**overrides: object) -> WorkflowInput:
    """Build a test WorkflowInput."""
    defaults = {
        "run_id": "test_run",
        "resume_path": "/tmp/resume.pdf",
        "preferences_text": "Python remote",
        "dry_run": False,
        "default_queue": "q-default",
        "llm_queue": "q-llm",
        "scraping_queue": "q-scraping",
    }
    defaults.update(overrides)
    return WorkflowInput(**defaults)  # type: ignore[arg-type]


class TestBuildInitialSnapshot:
    """Tests for _build_initial_snapshot."""

    def test_contains_all_required_keys(self) -> None:
        """Snapshot has all PipelineState keys."""
        input = _make_workflow_input()
        snapshot = JobHuntWorkflow._build_initial_snapshot(input)

        assert snapshot["config"]["run_id"] == "test_run"
        assert snapshot["config"]["resume_path"] == "/tmp/resume.pdf"
        assert snapshot["profile"] is None
        assert snapshot["companies"] == []
        assert snapshot["raw_jobs"] == []
        assert snapshot["total_tokens"] == 0

    def test_preserves_company_limit(self) -> None:
        """Company limit propagated to snapshot config."""
        input = _make_workflow_input(company_limit=3)
        snapshot = JobHuntWorkflow._build_initial_snapshot(input)
        assert snapshot["config"]["company_limit"] == 3


class TestBuildOutput:
    """Tests for _build_output."""

    def test_success_with_results(self) -> None:
        """Output built from final snapshot with scored jobs."""
        snapshot = {
            "companies": [{"id": "1"}, {"id": "2"}],
            "raw_jobs": [
                {"company_id": "1", "title": "A"},
                {"company_id": "2", "title": "B"},
            ],
            "scored_jobs": [{"score": 85}],
            "errors": [],
            "run_result": {
                "output_files": ["/out/results.csv"],
                "email_sent": True,
            },
        }
        output = JobHuntWorkflow._build_output(snapshot, 500, 0.25, 42.0)

        assert isinstance(output, WorkflowOutput)
        assert output.status == "success"
        assert output.companies_attempted == 2
        assert output.companies_succeeded == 2
        assert output.jobs_scraped == 2
        assert output.jobs_scored == 1
        assert output.total_tokens_used == 500
        assert output.estimated_cost_usd == 0.25
        assert output.duration_seconds == 42.0
        assert output.output_files == ["/out/results.csv"]
        assert output.email_sent is True

    def test_empty_snapshot(self) -> None:
        """Output handles empty snapshot gracefully."""
        snapshot = {
            "companies": [],
            "raw_jobs": [],
            "scored_jobs": [],
            "errors": [],
        }
        output = JobHuntWorkflow._build_output(snapshot, 0, 0.0, 1.0)
        assert output.companies_attempted == 0
        assert output.jobs_scraped == 0


class TestExtract:
    """Tests for _extract helper."""

    def test_returns_tuple(self) -> None:
        """Extracts snapshot, tokens, and cost."""
        from job_hunter_agents.orchestrator.temporal_payloads import StepResult

        result = StepResult(
            state_snapshot={"key": "val"},
            tokens_used=42,
            cost_usd=0.05,
        )
        snapshot, tokens, cost = JobHuntWorkflow._extract(result)
        assert snapshot == {"key": "val"}
        assert tokens == 42
        assert cost == pytest.approx(0.05)
