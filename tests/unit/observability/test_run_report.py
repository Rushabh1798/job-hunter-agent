"""Tests for observability/run_report.py."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from job_hunter_agents.observability.run_report import (
    MOCK_MANIFESTS,
    AgentStep,
    RunReport,
    format_run_report,
    generate_run_report,
)


def _make_span(
    name: str,
    attributes: dict[str, object] | None = None,
    start_time: int = 0,
    end_time: int = 1_000_000,
) -> SimpleNamespace:
    """Create a fake span object mimicking ReadableSpan."""
    return SimpleNamespace(
        name=name,
        attributes=attributes or {},
        start_time=start_time,
        end_time=end_time,
    )


@pytest.mark.unit
class TestGenerateRunReport:
    """Tests for generate_run_report."""

    def test_empty_spans_returns_default_report(self) -> None:
        """No spans → report with empty fields."""
        report = generate_run_report([], mock_mode="dry_run")
        assert report.run_id == ""
        assert report.pipeline_status == "unknown"
        assert report.agent_steps == []
        assert report.mock_mode == "dry_run"
        assert report.component_manifest == MOCK_MANIFESTS["dry_run"]

    def test_root_span_attributes_extracted(self) -> None:
        """Root span attributes populate the report."""
        root = _make_span(
            "pipeline.run",
            {
                "pipeline.run_id": "test-run-123",
                "pipeline.status": "success",
                "pipeline.total_tokens": 3000,
                "pipeline.total_cost_usd": 0.015,
                "pipeline.jobs_scored": 5,
                "pipeline.errors": 1,
            },
            start_time=0,
            end_time=500_000_000,  # 500ms in ns
        )
        report = generate_run_report([root], mock_mode="integration")
        assert report.run_id == "test-run-123"
        assert report.pipeline_status == "success"
        assert report.total_tokens == 3000
        assert report.total_cost_usd == 0.015
        assert report.jobs_scored == 5
        assert report.error_count == 1
        assert report.total_duration_ms == 500.0

    def test_agent_spans_sorted_by_start_time(self) -> None:
        """Agent steps appear in chronological order."""
        spans = [
            _make_span(
                "agent.score_jobs",
                {"agent.name": "score_jobs", "agent.status": "ok", "agent.tokens": 1500},
                start_time=200_000_000,
                end_time=300_000_000,
            ),
            _make_span(
                "agent.parse_resume",
                {"agent.name": "parse_resume", "agent.status": "ok", "agent.tokens": 500},
                start_time=0,
                end_time=100_000_000,
            ),
        ]
        report = generate_run_report(spans, mock_mode="dry_run")
        assert len(report.agent_steps) == 2
        assert report.agent_steps[0].name == "parse_resume"
        assert report.agent_steps[1].name == "score_jobs"
        assert report.agent_steps[0].order == 1
        assert report.agent_steps[1].order == 2

    def test_agent_error_captured(self) -> None:
        """Error attribute on agent span flows into report."""
        spans = [
            _make_span(
                "agent.scrape_jobs",
                {
                    "agent.name": "scrape_jobs",
                    "agent.status": "error",
                    "agent.error": "timeout after 30s",
                    "agent.tokens": 0,
                },
            ),
        ]
        report = generate_run_report(spans)
        assert report.agent_steps[0].status == "error"
        assert report.agent_steps[0].error == "timeout after 30s"

    def test_integration_mode_manifest(self) -> None:
        """Integration mode shows correct mocked/real components."""
        report = generate_run_report([], mock_mode="integration")
        manifest = report.component_manifest
        assert manifest["LLM (Anthropic)"] == "mocked"
        assert "real" in manifest["Search Provider"]
        assert "real" in manifest["Page Scraper (crawl4ai)"]
        assert "real" in manifest["ATS Clients"]

    def test_live_mode_manifest(self) -> None:
        """Live mode shows all components as real."""
        report = generate_run_report([], mock_mode="live")
        manifest = report.component_manifest
        assert manifest["LLM (Anthropic)"] == "real"
        assert manifest["PDF Parser"] == "real"
        assert manifest["Email Sender"] == "real"


@pytest.mark.unit
class TestFormatRunReport:
    """Tests for format_run_report."""

    def test_format_contains_key_sections(self) -> None:
        """Formatted output includes all expected section headers."""
        report = RunReport(
            run_id="fmt-test",
            pipeline_status="success",
            total_duration_ms=1234.0,
            total_tokens=3000,
            total_cost_usd=0.015,
            jobs_scored=5,
            error_count=0,
            mock_mode="dry_run",
            component_manifest=MOCK_MANIFESTS["dry_run"],
            agent_steps=[
                AgentStep(
                    order=1,
                    name="parse_resume",
                    duration_ms=50.0,
                    status="ok",
                    tokens=500,
                    error=None,
                ),
            ],
        )
        output = format_run_report(report)
        assert "PIPELINE RUN REPORT" in output
        assert "COMPONENT STATUS" in output
        assert "AGENT EXECUTION FLOW" in output
        assert "EXECUTION FLOW" in output
        assert "fmt-test" in output
        assert "parse_resume" in output
        assert "[MOCK]" in output

    def test_format_shows_error_detail(self) -> None:
        """Formatted output includes error details for failed steps."""
        report = RunReport(
            run_id="err-test",
            pipeline_status="partial",
            total_duration_ms=500.0,
            total_tokens=100,
            total_cost_usd=0.001,
            jobs_scored=0,
            error_count=1,
            mock_mode="dry_run",
            component_manifest=MOCK_MANIFESTS["dry_run"],
            agent_steps=[
                AgentStep(
                    order=1,
                    name="scrape_jobs",
                    duration_ms=300.0,
                    status="error",
                    tokens=0,
                    error="connection refused",
                ),
            ],
        )
        output = format_run_report(report)
        assert "[ERR]" in output
        assert "connection refused" in output

    def test_format_empty_steps(self) -> None:
        """Empty agent steps produce a placeholder message."""
        report = RunReport(
            run_id="empty",
            pipeline_status="unknown",
            total_duration_ms=0.0,
            total_tokens=0,
            total_cost_usd=0.0,
            jobs_scored=0,
            error_count=0,
            mock_mode="dry_run",
            component_manifest=MOCK_MANIFESTS["dry_run"],
            agent_steps=[],
        )
        output = format_run_report(report)
        assert "(no agent spans captured)" in output
