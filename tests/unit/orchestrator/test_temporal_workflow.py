"""Unit tests for Temporal workflow definition."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from job_hunter_agents.orchestrator.temporal_payloads import (
    ScrapeCompanyResult,
    StepResult,
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


def _make_step_result(
    snapshot: dict[str, Any] | None = None,
    tokens: int = 50,
    cost: float = 0.01,
) -> StepResult:
    """Build a StepResult with defaults."""
    return StepResult(
        state_snapshot=snapshot or _make_snapshot(),
        tokens_used=tokens,
        cost_usd=cost,
    )


def _make_snapshot(**overrides: object) -> dict[str, Any]:
    """Build a minimal state snapshot."""
    base: dict[str, Any] = {
        "config": {
            "run_id": "test_run",
            "resume_path": "/tmp/resume.pdf",
            "preferences_text": "Python dev",
        },
        "profile": None,
        "preferences": None,
        "companies": [],
        "raw_jobs": [],
        "normalized_jobs": [],
        "scored_jobs": [],
        "errors": [],
        "total_tokens": 0,
        "total_cost_usd": 0.0,
    }
    base.update(overrides)
    return base


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
        snapshot: dict[str, list[object]] = {
            "companies": [],
            "raw_jobs": [],
            "scored_jobs": [],
            "errors": [],
        }
        output = JobHuntWorkflow._build_output(snapshot, 0, 0.0, 1.0)
        assert output.companies_attempted == 0
        assert output.jobs_scraped == 0

    def test_output_with_non_dict_run_result(self) -> None:
        """Output handles non-dict run_result gracefully."""
        snapshot: dict[str, Any] = {
            "companies": [],
            "raw_jobs": [],
            "scored_jobs": [],
            "errors": [],
            "run_result": "not_a_dict",
        }
        output = JobHuntWorkflow._build_output(snapshot, 0, 0.0, 1.0)
        assert output.output_files == []
        assert output.email_sent is False


class TestExtract:
    """Tests for _extract helper."""

    def test_returns_tuple(self) -> None:
        """Extracts snapshot, tokens, and cost."""
        result = StepResult(
            state_snapshot={"key": "val"},
            tokens_used=42,
            cost_usd=0.05,
        )
        snapshot, tokens, cost = JobHuntWorkflow._extract(result)
        assert snapshot == {"key": "val"}
        assert tokens == 42
        assert cost == pytest.approx(0.05)


class TestScrapeParallel:
    """Tests for _scrape_parallel."""

    @pytest.mark.asyncio
    async def test_empty_companies(self) -> None:
        """No companies means no scraping."""
        wf = JobHuntWorkflow()
        input = _make_workflow_input()
        snapshot = _make_snapshot(companies=[])

        result_snapshot, tokens, cost = await wf._scrape_parallel(snapshot, input)
        assert tokens == 0
        assert cost == 0.0
        assert result_snapshot["raw_jobs"] == []

    @pytest.mark.asyncio
    async def test_parallel_scraping_merges_results(self) -> None:
        """Scrape results from multiple companies are merged."""
        wf = JobHuntWorkflow()
        input = _make_workflow_input()
        snapshot = _make_snapshot(
            companies=[
                {"name": "Co1", "career_url": "https://co1.com"},
                {"name": "Co2", "career_url": "https://co2.com"},
            ],
            config={"run_id": "test"},
        )

        result1 = ScrapeCompanyResult(
            raw_jobs=[{"title": "Job1", "company_id": "1"}],
            tokens_used=100,
            cost_usd=0.01,
            errors=[],
        )
        result2 = ScrapeCompanyResult(
            raw_jobs=[{"title": "Job2", "company_id": "2"}],
            tokens_used=200,
            cost_usd=0.02,
            errors=[{"error": "timeout"}],
        )

        with patch(
            "job_hunter_agents.orchestrator.temporal_workflow.workflow"
        ) as mock_wf:
            mock_wf.execute_activity = AsyncMock(side_effect=[result1, result2])

            result_snapshot, tokens, cost = await wf._scrape_parallel(snapshot, input)

        assert len(result_snapshot["raw_jobs"]) == 2
        assert tokens == 300
        assert cost == pytest.approx(0.03)
        assert len(result_snapshot["errors"]) == 1


class TestRunStep:
    """Tests for _run_step."""

    @pytest.mark.asyncio
    async def test_run_step_calls_execute_activity(self) -> None:
        """_run_step delegates to workflow.execute_activity."""
        wf = JobHuntWorkflow()
        expected_result = _make_step_result()

        with patch(
            "job_hunter_agents.orchestrator.temporal_workflow.workflow"
        ) as mock_wf:
            mock_wf.execute_activity = AsyncMock(return_value=expected_result)

            from job_hunter_agents.orchestrator.temporal_workflow import _DEFAULT_RETRY

            result = await wf._run_step(
                "parse_resume", _make_snapshot(), "q-default", _DEFAULT_RETRY, minutes=2
            )

        assert result.tokens_used == 50
        mock_wf.execute_activity.assert_called_once()
