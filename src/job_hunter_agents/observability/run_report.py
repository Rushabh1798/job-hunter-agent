"""Pipeline run report generator from OTEL spans.

Collects span data from InMemorySpanExporter and produces a structured
report showing component status (real vs mocked), agent timing, flow
linkage, and summary statistics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Mock manifests — define what is mocked in each test mode
# ---------------------------------------------------------------------------

MOCK_MANIFESTS: dict[str, dict[str, str]] = {
    "dry_run": {
        "LLM (Anthropic)": "mocked",
        "PDF Parser": "mocked",
        "Search Provider": "mocked",
        "Page Scraper (crawl4ai)": "mocked",
        "ATS Clients": "mocked",
        "Email Sender": "mocked",
        "Database": "real (settings-dependent)",
        "Cache": "real (settings-dependent)",
    },
    "integration": {
        "LLM (Anthropic)": "mocked",
        "PDF Parser": "mocked",
        "Search Provider": "real (DuckDuckGo)",
        "Page Scraper (crawl4ai)": "real",
        "ATS Clients": "real (public APIs)",
        "Email Sender": "mocked",
        "Database": "real (PostgreSQL)",
        "Cache": "real (Redis)",
    },
    "live": {
        "LLM (Anthropic)": "real",
        "PDF Parser": "real",
        "Search Provider": "real (Tavily)",
        "Page Scraper (crawl4ai)": "real",
        "ATS Clients": "real (public APIs)",
        "Email Sender": "real",
        "Database": "real (PostgreSQL)",
        "Cache": "real (Redis)",
    },
}


# ---------------------------------------------------------------------------
# Report data structures
# ---------------------------------------------------------------------------


@dataclass
class AgentStep:
    """Execution data for a single pipeline agent step."""

    order: int
    name: str
    duration_ms: float
    status: str
    tokens: int
    error: str | None


@dataclass
class RunReport:
    """Structured report for a pipeline run."""

    run_id: str
    pipeline_status: str
    total_duration_ms: float
    total_tokens: int
    total_cost_usd: float
    jobs_scored: int
    error_count: int
    mock_mode: str
    component_manifest: dict[str, str]
    agent_steps: list[AgentStep] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Report generation from OTEL spans
# ---------------------------------------------------------------------------


def generate_run_report(
    spans: list[Any],
    mock_mode: str = "dry_run",
) -> RunReport:
    """Build a RunReport from InMemorySpanExporter finished spans.

    Args:
        spans: List of ReadableSpan objects from InMemorySpanExporter.
        mock_mode: One of 'dry_run', 'integration', 'live'.

    Returns:
        Structured RunReport with agent timing and component status.
    """
    manifest = MOCK_MANIFESTS.get(mock_mode, MOCK_MANIFESTS["dry_run"])

    # Find the root pipeline span
    root_span = _find_root_span(spans)

    run_id = ""
    pipeline_status = "unknown"
    total_tokens = 0
    total_cost_usd = 0.0
    jobs_scored = 0
    error_count = 0
    total_duration_ms = 0.0

    if root_span is not None:
        attrs = dict(root_span.attributes or {})
        run_id = str(attrs.get("pipeline.run_id", ""))
        pipeline_status = str(attrs.get("pipeline.status", "unknown"))
        total_tokens = int(attrs.get("pipeline.total_tokens", 0))
        total_cost_usd = float(attrs.get("pipeline.total_cost_usd", 0.0))
        jobs_scored = int(attrs.get("pipeline.jobs_scored", 0))
        error_count = int(attrs.get("pipeline.errors", 0))
        total_duration_ms = _span_duration_ms(root_span)

    # Extract agent steps sorted by start time
    agent_spans = _extract_agent_spans(spans)
    agent_steps = []
    for i, aspan in enumerate(agent_spans, start=1):
        attrs = dict(aspan.attributes or {})
        agent_steps.append(
            AgentStep(
                order=i,
                name=str(attrs.get("agent.name", aspan.name)),
                duration_ms=_span_duration_ms(aspan),
                status=str(attrs.get("agent.status", "unknown")),
                tokens=int(attrs.get("agent.tokens", 0)),
                error=attrs.get("agent.error"),  # type: ignore[arg-type]
            )
        )

    return RunReport(
        run_id=run_id,
        pipeline_status=pipeline_status,
        total_duration_ms=total_duration_ms,
        total_tokens=total_tokens,
        total_cost_usd=total_cost_usd,
        jobs_scored=jobs_scored,
        error_count=error_count,
        mock_mode=mock_mode,
        component_manifest=manifest,
        agent_steps=agent_steps,
    )


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

_STATUS_ICONS = {"ok": "[OK]", "error": "[ERR]", "unknown": "[?]"}
_MODE_LABELS = {"mocked": "[MOCK]", "real": "[REAL]"}


def format_run_report(report: RunReport) -> str:
    """Format a RunReport as a human-readable text block.

    Designed for pytest -s output — prints clearly in terminal.
    """
    lines: list[str] = []
    sep = "=" * 72

    lines.append("")
    lines.append(sep)
    lines.append("  PIPELINE RUN REPORT")
    lines.append(sep)
    lines.append(f"  Run ID:    {report.run_id}")
    lines.append(f"  Status:    {report.pipeline_status}")
    lines.append(
        f"  Duration:  {report.total_duration_ms:.0f}ms"
        f"  |  Tokens: {report.total_tokens}"
        f"  |  Cost: ${report.total_cost_usd:.4f}"
    )
    lines.append(f"  Jobs:      {report.jobs_scored} scored  |  Errors: {report.error_count}")
    lines.append(f"  Mode:      {report.mock_mode}")
    lines.append("")

    # --- Component status ---
    lines.append("-" * 72)
    lines.append("  COMPONENT STATUS")
    lines.append("-" * 72)
    lines.append(f"  {'Component':<28} {'Status':<40}")
    lines.append(f"  {'-' * 27} {'-' * 39}")
    for comp_name, comp_status in report.component_manifest.items():
        mode_tag = _MODE_LABELS.get(comp_status, "[REAL]")
        if "mocked" in comp_status:
            mode_tag = "[MOCK]"
        lines.append(f"  {comp_name:<28} {mode_tag:<8} {comp_status}")
    lines.append("")

    # --- Agent execution flow ---
    lines.append("-" * 72)
    lines.append("  AGENT EXECUTION FLOW")
    lines.append("-" * 72)
    lines.append(f"  {'#':<4} {'Agent':<22} {'Duration':<12} {'Status':<10} {'Tokens':<10}")
    lines.append(f"  {'-' * 3} {'-' * 21} {'-' * 11} {'-' * 9} {'-' * 9}")

    for step in report.agent_steps:
        status_icon = _STATUS_ICONS.get(step.status, "[?]")
        dur_str = f"{step.duration_ms:.0f}ms"
        lines.append(
            f"  {step.order:<4} {step.name:<22} {dur_str:<12} {status_icon:<10} {step.tokens}"
        )
        if step.error:
            lines.append(f"       -> Error: {step.error}")

    if not report.agent_steps:
        lines.append("  (no agent spans captured)")

    # --- Flow linkage ---
    lines.append("")
    lines.append("-" * 72)
    lines.append("  EXECUTION FLOW")
    lines.append("-" * 72)
    if report.agent_steps:
        flow_names = [s.name for s in report.agent_steps]
        flow_str = " -> ".join(flow_names)
        lines.append(f"  {flow_str}")
    else:
        lines.append("  (no flow data)")

    lines.append(sep)
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_root_span(spans: list[Any]) -> Any | None:  # noqa: ANN401
    """Find the pipeline.run root span."""
    for span in spans:
        if span.name == "pipeline.run":
            return span
    return None


def _extract_agent_spans(spans: list[Any]) -> list[Any]:
    """Extract agent spans, sorted by start time."""
    agent_spans = [s for s in spans if s.name.startswith("agent.")]
    return sorted(agent_spans, key=lambda s: s.start_time or 0)


def _span_duration_ms(span: Any) -> float:  # noqa: ANN401
    """Calculate span duration in milliseconds from nanosecond timestamps."""
    start = getattr(span, "start_time", None)
    end = getattr(span, "end_time", None)
    if start is not None and end is not None:
        return float((end - start) / 1_000_000)  # ns -> ms
    return 0.0
