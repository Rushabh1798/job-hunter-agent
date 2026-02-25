"""Shared mock Settings factory."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def make_settings(**overrides: object) -> MagicMock:
    """Create a mock Settings with sensible defaults.

    All agents and pipeline code rely on these fields. Override any
    attribute via keyword arguments.
    """
    settings = MagicMock()
    settings.anthropic_api_key.get_secret_value.return_value = "test-key"
    settings.haiku_model = "claude-haiku-4-5-20251001"
    settings.sonnet_model = "claude-sonnet-4-5-20250514"
    settings.max_cost_per_run_usd = 5.0
    settings.warn_cost_threshold_usd = 2.0
    settings.checkpoint_enabled = False
    settings.checkpoint_dir = Path("/tmp/checkpoints")
    settings.agent_timeout_seconds = 300
    settings.log_level = "INFO"
    settings.db_backend = "sqlite"
    settings.embedding_provider = "local"
    settings.cache_backend = "db"
    settings.otel_exporter = "none"
    settings.otel_endpoint = "http://localhost:4317"
    settings.otel_service_name = "job-hunter-test"

    for key, value in overrides.items():
        setattr(settings, key, value)

    return settings
