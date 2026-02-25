"""Shared pytest fixtures for unit tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from job_hunter_core.models.candidate import CandidateProfile, SearchPreferences
from job_hunter_core.state import PipelineState
from tests.mocks.mock_factories import (
    make_candidate_profile,
    make_pipeline_state,
    make_search_preferences,
)
from tests.mocks.mock_settings import make_settings


@pytest.fixture
def mock_settings() -> MagicMock:
    """Return a MagicMock Settings with sensible defaults."""
    return make_settings()


@pytest.fixture
def pipeline_state() -> PipelineState:
    """Return a fresh PipelineState with default RunConfig."""
    return make_pipeline_state()


@pytest.fixture
def sample_profile() -> CandidateProfile:
    """Return a minimal valid CandidateProfile."""
    return make_candidate_profile()


@pytest.fixture
def sample_prefs() -> SearchPreferences:
    """Return a minimal valid SearchPreferences."""
    return make_search_preferences()


@pytest.fixture
def tmp_checkpoint_dir(tmp_path: Path) -> Path:
    """Return a temporary directory for checkpoint files."""
    d = tmp_path / "checkpoints"
    d.mkdir()
    return d
