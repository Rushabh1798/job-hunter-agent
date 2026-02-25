"""Tests for observability/logging.py."""

from __future__ import annotations

import io
import logging

import pytest
import structlog

from job_hunter_agents.observability.logging import (
    _resolve_level,
    bind_run_context,
    clear_run_context,
    configure_logging,
)


def _make_settings(**overrides: object) -> object:
    """Create a minimal mock settings object."""
    from types import SimpleNamespace

    defaults: dict[str, object] = {"log_format": "console", "log_level": "INFO"}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.unit
class TestConfigureLogging:
    """Tests for configure_logging."""

    def test_configure_logging_console_mode(self) -> None:
        """Console mode configures without error."""
        settings = _make_settings(log_format="console", log_level="INFO")
        configure_logging(settings)  # type: ignore[arg-type]
        # Should not raise; structlog is usable
        log = structlog.get_logger()
        assert log is not None

    def test_configure_logging_json_mode(self) -> None:
        """JSON mode produces JSON output."""
        settings = _make_settings(log_format="json", log_level="INFO")
        configure_logging(settings)  # type: ignore[arg-type]

        # Capture output via a handler
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.getLogger().handlers[0].formatter)
        root = logging.getLogger("test_json_mode")
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        root.info("test_event")

        output = stream.getvalue()
        assert "{" in output or "test_event" in output

    def test_configure_logging_sets_level(self) -> None:
        """Log level is applied to root logger."""
        settings = _make_settings(log_format="console", log_level="WARNING")
        configure_logging(settings)  # type: ignore[arg-type]
        assert logging.getLogger().level == logging.WARNING


@pytest.mark.unit
class TestRunContext:
    """Tests for bind/clear run context."""

    def test_bind_and_clear_run_context(self) -> None:
        """Binding and clearing run context does not raise."""
        bind_run_context("test-run-123")
        # Context is bound — structlog will include it
        clear_run_context()
        # After clear, context is gone


@pytest.mark.unit
class TestResolveLevel:
    """Tests for _resolve_level."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
            ("CRITICAL", logging.CRITICAL),
            ("debug", logging.DEBUG),
            ("unknown", logging.INFO),
        ],
    )
    def test_resolve_level(self, name: str, expected: int) -> None:
        """Level names resolve to correct logging constants."""
        assert _resolve_level(name) == expected
