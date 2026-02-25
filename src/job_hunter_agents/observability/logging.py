"""Structured logging configuration using structlog."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars

if TYPE_CHECKING:
    from job_hunter_core.config.settings import Settings


def configure_logging(settings: Settings) -> None:
    """Configure structlog with JSON or console rendering.

    Sets up shared processors, routes stdlib logging through structlog,
    and configures the output format based on settings.
    """
    shared_processors: list[structlog.types.Processor] = [
        merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.log_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    level = _resolve_level(settings.log_level)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # Quiet noisy third-party loggers
    for name in ("httpx", "httpcore", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(max(level, logging.WARNING))


def bind_run_context(run_id: str) -> None:
    """Bind run_id to all subsequent log entries via contextvars."""
    bind_contextvars(run_id=run_id)


def clear_run_context() -> None:
    """Clear all bound context variables."""
    clear_contextvars()


def _resolve_level(level_name: str) -> int:
    """Convert a level name string to a logging level int."""
    mapping: dict[str, int] = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return mapping.get(level_name.upper(), logging.INFO)
