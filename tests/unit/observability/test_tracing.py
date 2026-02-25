"""Tests for observability/tracing.py."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from job_hunter_agents.observability import tracing
from job_hunter_agents.observability.tracing import (
    _maybe_init_langsmith,
    configure_tracing,
    configure_tracing_with_exporter,
    disable_tracing,
    get_tracer,
    trace_pipeline_run,
    traced_agent,
)


def _make_settings(**overrides: object) -> SimpleNamespace:
    """Create a minimal mock settings object."""
    defaults: dict[str, object] = {
        "otel_exporter": "none",
        "otel_endpoint": "http://localhost:4317",
        "otel_service_name": "test-service",
        "langsmith_api_key": None,
        "langsmith_project": "test-project",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.unit
class TestConfigureTracing:
    """Tests for configure_tracing."""

    def test_configure_tracing_none(self) -> None:
        """'none' exporter sets _tracer to None."""
        settings = _make_settings(otel_exporter="none")
        configure_tracing(settings)  # type: ignore[arg-type]
        assert tracing._tracer is None

    def test_configure_tracing_console(self) -> None:
        """'console' exporter creates a tracer."""
        pytest.importorskip("opentelemetry")
        settings = _make_settings(otel_exporter="console")
        configure_tracing(settings)  # type: ignore[arg-type]
        assert tracing._tracer is not None
        # Reset to avoid polluting other tests
        tracing._tracer = None


@pytest.mark.unit
class TestTracedAgent:
    """Tests for traced_agent decorator."""

    @pytest.mark.asyncio
    async def test_traced_agent_noop_when_disabled(self) -> None:
        """Decorated function runs normally when tracing is disabled."""
        original_tracer = tracing._tracer
        tracing._tracer = None

        @traced_agent("test_agent")
        async def my_agent(x: int) -> int:
            return x * 2

        result = await my_agent(5)
        assert result == 10
        tracing._tracer = original_tracer

    @pytest.mark.asyncio
    async def test_traced_agent_creates_span(self) -> None:
        """When tracer is active, a span is created."""
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        original_tracer = tracing._tracer
        tracing._tracer = mock_tracer

        @traced_agent("scorer")
        async def my_agent() -> str:
            return "done"

        result = await my_agent()
        assert result == "done"
        mock_tracer.start_as_current_span.assert_called_once_with("agent.scorer")
        mock_span.set_attribute.assert_any_call("agent.name", "scorer")

        tracing._tracer = original_tracer


@pytest.mark.unit
class TestTracePipelineRun:
    """Tests for trace_pipeline_run."""

    @pytest.mark.asyncio
    async def test_trace_pipeline_run_noop(self) -> None:
        """Context manager yields None when tracing is disabled."""
        original_tracer = tracing._tracer
        tracing._tracer = None

        async with trace_pipeline_run("run-123") as span:
            assert span is None

        tracing._tracer = original_tracer


@pytest.mark.unit
class TestLangSmith:
    """Tests for LangSmith env var setup."""

    def test_langsmith_env_set_when_key_present(self) -> None:
        """Sets LANGCHAIN_* env vars when API key is provided."""
        mock_key = MagicMock()
        mock_key.get_secret_value.return_value = "ls-test-key-123"

        settings = _make_settings(
            langsmith_api_key=mock_key,
            langsmith_project="my-project",
        )

        with patch.dict(os.environ, {}, clear=False):
            _maybe_init_langsmith(settings)  # type: ignore[arg-type]
            assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
            assert os.environ.get("LANGCHAIN_API_KEY") == "ls-test-key-123"
            assert os.environ.get("LANGCHAIN_PROJECT") == "my-project"

    def test_langsmith_env_not_set_when_no_key(self) -> None:
        """Does not set env vars when API key is None."""
        settings = _make_settings(langsmith_api_key=None)

        with patch.dict(os.environ, {}, clear=False):
            original = os.environ.get("LANGCHAIN_TRACING_V2")
            _maybe_init_langsmith(settings)  # type: ignore[arg-type]
            # Should not have changed
            assert os.environ.get("LANGCHAIN_TRACING_V2") == original


@pytest.mark.unit
class TestTracingHelpers:
    """Tests for get_tracer, configure_tracing_with_exporter, disable_tracing."""

    def test_get_tracer_returns_none_when_disabled(self) -> None:
        """get_tracer() is None when tracing is off."""
        original = tracing._tracer
        tracing._tracer = None
        assert get_tracer() is None
        tracing._tracer = original

    def test_get_tracer_returns_tracer_when_configured(self) -> None:
        """get_tracer() returns a tracer after configure_tracing_with_exporter."""
        pytest.importorskip("opentelemetry")
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        configure_tracing_with_exporter("test-svc", InMemorySpanExporter())
        assert get_tracer() is not None
        disable_tracing()

    def test_disable_tracing_resets(self) -> None:
        """disable_tracing() sets tracer to None."""
        pytest.importorskip("opentelemetry")
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        configure_tracing_with_exporter("test-svc", InMemorySpanExporter())
        assert get_tracer() is not None
        disable_tracing()
        assert get_tracer() is None

    def test_configure_with_exporter_creates_spans(self) -> None:
        """Spans are captured by InMemorySpanExporter."""
        pytest.importorskip("opentelemetry")
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        exporter = InMemorySpanExporter()
        configure_tracing_with_exporter("test-svc", exporter)

        tracer = get_tracer()
        assert tracer is not None
        with tracer.start_as_current_span("test-span") as span:
            span.set_attribute("key", "value")

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "test-span"
        disable_tracing()
