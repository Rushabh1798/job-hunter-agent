"""OpenTelemetry tracing and LangSmith integration."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from functools import wraps
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

import structlog

if TYPE_CHECKING:
    from job_hunter_core.config.settings import Settings

logger = structlog.get_logger()

# Module-level tracer — set by configure_tracing(), remains None if disabled.
_tracer: Any = None

P = ParamSpec("P")
R = TypeVar("R")


def configure_tracing(settings: Settings) -> None:
    """Configure OpenTelemetry tracing based on settings.

    All OTEL imports are deferred so --lite mode never loads them.
    Also initialises LangSmith env vars if an API key is present.
    """
    global _tracer

    _maybe_init_langsmith(settings)

    if settings.otel_exporter == "none":
        _tracer = None
        return

    # Deferred imports — only loaded when tracing is enabled
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter == "console":
        from opentelemetry.sdk.trace.export import (
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )

        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    elif settings.otel_exporter == "otlp":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("job-hunter-agent")
    logger.info("tracing_configured", exporter=settings.otel_exporter)


def traced_agent(
    agent_name: str,
) -> Callable[
    [Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]
]:
    """Async decorator that wraps an agent run in an OTEL span.

    Noop when tracing is disabled (_tracer is None).
    """

    def decorator(
        fn: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if _tracer is None:
                return await fn(*args, **kwargs)

            with _tracer.start_as_current_span(f"agent.{agent_name}") as span:
                span.set_attribute("agent.name", agent_name)
                start = time.monotonic()
                try:
                    result = await fn(*args, **kwargs)
                    span.set_attribute("agent.status", "ok")
                    return result
                except Exception as exc:
                    span.set_attribute("agent.status", "error")
                    span.set_attribute("agent.error", str(exc))
                    raise
                finally:
                    elapsed = time.monotonic() - start
                    span.set_attribute("agent.duration_seconds", round(elapsed, 3))

        return wrapper

    return decorator


@asynccontextmanager
async def trace_pipeline_run(run_id: str) -> AsyncGenerator[Any, None]:
    """Context manager that creates a root span for the entire pipeline run.

    Yields the span (or None if tracing is disabled).
    """
    if _tracer is None:
        yield None
        return

    with _tracer.start_as_current_span("pipeline.run") as span:
        span.set_attribute("pipeline.run_id", run_id)
        yield span


def _maybe_init_langsmith(settings: Settings) -> None:
    """Set LangSmith env vars if an API key is configured."""
    if settings.langsmith_api_key is not None:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = (
            settings.langsmith_api_key.get_secret_value()
        )
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
        logger.info("langsmith_configured", project=settings.langsmith_project)
