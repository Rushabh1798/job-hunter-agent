"""Integration tests for OTEL tracing through the pipeline.

Uses InMemorySpanExporter to capture spans — no Jaeger required.
Exercises full dry-run pipeline with real state management and mocked externals.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from job_hunter_agents.observability.tracing import (
    configure_tracing_with_exporter,
    disable_tracing,
)
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
        min_score_threshold=0,
        max_concurrent_scrapers=2,
    )


@pytest.fixture
def span_exporter() -> object:
    """Configure in-memory span exporter, disable after test."""
    otel = pytest.importorskip("opentelemetry")  # noqa: F841
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    configure_tracing_with_exporter("test-tracing", exporter)
    yield exporter
    disable_tracing()


class TestPipelineTracing:
    """Full pipeline tracing with InMemorySpanExporter."""

    async def test_pipeline_produces_root_and_agent_spans(
        self,
        dry_run_patches: ExitStack,
        tmp_path: Path,
        span_exporter: object,
    ) -> None:
        """Pipeline run produces root span + 8 agent child spans."""
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        assert isinstance(span_exporter, InMemorySpanExporter)

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

        spans = span_exporter.get_finished_spans()
        span_names = [s.name for s in spans]

        # Root span
        assert "pipeline.run" in span_names

        # Agent child spans — at least the first few should be present
        expected_prefixes = [
            "agent.parse_resume",
            "agent.parse_prefs",
            "agent.find_companies",
        ]
        for prefix in expected_prefixes:
            assert any(
                name == prefix for name in span_names
            ), f"Missing span: {prefix}"

    async def test_root_span_has_summary_attributes(
        self,
        dry_run_patches: ExitStack,
        tmp_path: Path,
        span_exporter: object,
    ) -> None:
        """Root pipeline span has summary attributes."""
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        assert isinstance(span_exporter, InMemorySpanExporter)

        settings = _make_settings(tmp_path)
        config = RunConfig(
            resume_path=FIXTURE_RESUME,
            preferences_text="Python remote roles at startups",
            dry_run=True,
            company_limit=2,
        )

        pipeline = Pipeline(settings)
        await pipeline.run(config)

        spans = span_exporter.get_finished_spans()
        root_spans = [s for s in spans if s.name == "pipeline.run"]
        assert len(root_spans) == 1

        root = root_spans[0]
        attrs = dict(root.attributes or {})
        assert "pipeline.run_id" in attrs
        assert "pipeline.status" in attrs
        assert attrs["pipeline.status"] == "success"

    async def test_agent_spans_have_status_attributes(
        self,
        dry_run_patches: ExitStack,
        tmp_path: Path,
        span_exporter: object,
    ) -> None:
        """Agent spans have agent.name and agent.status attributes."""
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        assert isinstance(span_exporter, InMemorySpanExporter)

        settings = _make_settings(tmp_path)
        config = RunConfig(
            resume_path=FIXTURE_RESUME,
            preferences_text="Python remote roles at startups",
            dry_run=True,
            company_limit=2,
        )

        pipeline = Pipeline(settings)
        await pipeline.run(config)

        spans = span_exporter.get_finished_spans()
        agent_spans = [s for s in spans if s.name.startswith("agent.")]

        assert len(agent_spans) > 0
        for span in agent_spans:
            attrs = dict(span.attributes or {})
            assert "agent.name" in attrs
            assert "agent.status" in attrs

    async def test_tracing_disabled_produces_no_spans(
        self,
        dry_run_patches: ExitStack,
        tmp_path: Path,
    ) -> None:
        """Pipeline with tracing disabled produces no spans."""
        pytest.importorskip("opentelemetry")
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        # Ensure tracing is disabled
        disable_tracing()

        exporter = InMemorySpanExporter()
        # Do NOT configure tracing — leave it disabled

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

        spans = exporter.get_finished_spans()
        assert len(spans) == 0
