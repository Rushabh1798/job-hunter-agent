"""Tests for Settings configuration."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from job_hunter_core.config.settings import Settings


def _base_env() -> dict[str, str]:
    """Return minimum required env vars for Settings."""
    return {
        "JH_ANTHROPIC_API_KEY": "sk-ant-test",
        "JH_TAVILY_API_KEY": "tvly-test",
    }


@pytest.mark.unit
class TestSettings:
    """Test Settings validation and defaults."""

    def test_default_settings(self) -> None:
        """Settings loads with required keys and correct defaults."""
        with patch.dict(os.environ, _base_env(), clear=False):
            s = Settings()  # type: ignore[call-arg]
        assert s.db_backend == "sqlite"
        assert s.embedding_provider == "local"
        assert s.embedding_dimension == 384
        assert s.max_cost_per_run_usd == 5.0

    def test_postgres_backend_sets_database_url(self) -> None:
        """When db_backend=postgres, database_url is set from postgres_url."""
        env = {**_base_env(), "JH_DB_BACKEND": "postgres"}
        with patch.dict(os.environ, env, clear=False):
            s = Settings()  # type: ignore[call-arg]
        assert s.database_url == s.postgres_url
        assert "asyncpg" in s.database_url

    def test_voyage_without_key_raises(self) -> None:
        """Voyage provider without API key raises ValueError."""
        env = {**_base_env(), "JH_EMBEDDING_PROVIDER": "voyage"}
        with patch.dict(os.environ, env, clear=False):
            with pytest.raises(ValidationError, match="voyage_api_key required"):
                Settings()  # type: ignore[call-arg]

    def test_voyage_with_key_sets_dimension(self) -> None:
        """Voyage provider sets embedding dimension to 1024."""
        env = {
            **_base_env(),
            "JH_EMBEDDING_PROVIDER": "voyage",
            "JH_VOYAGE_API_KEY": "voyage-test",
        }
        with patch.dict(os.environ, env, clear=False):
            s = Settings()  # type: ignore[call-arg]
        assert s.embedding_dimension == 1024

    def test_missing_anthropic_key_raises(self) -> None:
        """Missing anthropic_api_key raises validation error."""
        env = {"JH_TAVILY_API_KEY": "tvly-test"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError):
                Settings()  # type: ignore[call-arg]
