"""Shared mock Settings factory and real Settings factory for integration tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from job_hunter_core.config.settings import Settings


def make_settings(**overrides: object) -> MagicMock:
    """Create a mock Settings with sensible defaults.

    All agents and pipeline code rely on these fields. Override any
    attribute via keyword arguments.

    Uses llm_provider="fake" so BaseAgent builds a FakeLLMProvider
    from the llm-gateway registry — no patches needed.
    """
    settings = MagicMock()
    settings.llm_provider = "fake"
    settings.anthropic_api_key = None
    settings.haiku_model = "claude-haiku-4-5-20251001"
    settings.sonnet_model = "claude-sonnet-4-5-20250514"
    settings.max_cost_per_run_usd = 5.0
    settings.warn_cost_threshold_usd = 2.0
    settings.checkpoint_enabled = False
    settings.checkpoint_dir = Path("/tmp/checkpoints")
    settings.agent_timeout_seconds = 300
    settings.log_level = "INFO"
    settings.log_format = "console"
    settings.db_backend = "sqlite"
    settings.embedding_provider = "local"
    settings.cache_backend = "db"
    settings.otel_exporter = "none"
    settings.otel_endpoint = "http://localhost:4317"
    settings.otel_service_name = "job-hunter-test"
    settings.min_score_threshold = 60
    settings.min_recommended_jobs = 10
    settings.max_discovery_iterations = 3
    settings.max_concurrent_scrapers = 5
    settings.max_jobs_per_company = 10
    settings.top_k_semantic = 50
    settings.output_dir = Path("/tmp/output")
    settings.email_provider = "smtp"
    settings.smtp_host = "smtp.test.com"
    settings.smtp_port = 587
    settings.smtp_user = "user@test.com"
    settings.smtp_password = None
    settings.sendgrid_api_key = None
    settings.search_provider = "duckduckgo"

    for key, value in overrides.items():
        setattr(settings, key, value)

    return settings


def make_real_settings(tmp_path: Path, **overrides: object) -> Settings:
    """Create a real Settings instance for integration tests.

    Points at test Postgres + Redis containers. LLM uses fake provider
    (no API key needed). Search uses DuckDuckGo (free, no API key).
    """
    from job_hunter_core.config.settings import Settings as _Settings

    defaults: dict[str, object] = {
        "llm_provider": "fake",
        "anthropic_api_key": None,
        "tavily_api_key": "fake-key",
        "search_provider": "duckduckgo",
        "db_backend": "postgres",
        "postgres_url": "postgresql+asyncpg://postgres:dev@localhost:5432/jobhunter_test",
        "cache_backend": "redis",
        "redis_url": "redis://localhost:6379/1",
        "embedding_provider": "local",
        "output_dir": tmp_path / "output",
        "checkpoint_dir": tmp_path / "checkpoints",
        "checkpoint_enabled": True,
        "min_score_threshold": 0,
        "max_concurrent_scrapers": 2,
    }
    defaults.update(overrides)
    return _Settings(**defaults)  # type: ignore[arg-type]
