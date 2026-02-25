"""Integration tests for checkpoint file persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_hunter_agents.orchestrator.checkpoint import (
    load_latest_checkpoint,
    save_checkpoint,
)
from job_hunter_core.state import PipelineState
from tests.mocks.mock_factories import (
    make_candidate_profile,
    make_company,
    make_pipeline_state,
    make_search_preferences,
)

pytestmark = pytest.mark.integration


class TestCheckpointPersistence:
    """Checkpoint save/load against the real filesystem."""

    def test_save_checkpoint_writes_file(self, tmp_path: Path) -> None:
        """save_checkpoint creates a JSON file on disk."""
        state = make_pipeline_state()
        state.profile = make_candidate_profile()
        state.preferences = make_search_preferences()
        state.companies = [make_company()]
        state.total_tokens = 500
        state.total_cost_usd = 0.05

        checkpoint = state.to_checkpoint("find_companies")
        path = save_checkpoint(checkpoint, tmp_path)

        assert path.exists()
        assert path.name.endswith("--find_companies.json")
        data = json.loads(path.read_text())
        assert data["run_id"] == state.config.run_id
        assert data["completed_step"] == "find_companies"

    def test_load_latest_checkpoint(self, tmp_path: Path) -> None:
        """load_latest_checkpoint returns the most recent checkpoint."""
        state = make_pipeline_state(config__run_id="load-test") if False else make_pipeline_state()
        # Override run_id for this test
        state.config.run_id = "load-test"

        # Save two checkpoints
        cp1 = state.to_checkpoint("parse_resume")
        save_checkpoint(cp1, tmp_path)

        state.preferences = make_search_preferences()
        cp2 = state.to_checkpoint("parse_prefs")
        save_checkpoint(cp2, tmp_path)

        # Load should return the latest
        loaded = load_latest_checkpoint("load-test", tmp_path)
        assert loaded is not None
        assert loaded.completed_step == "parse_prefs"

    def test_full_roundtrip_preserves_fields(self, tmp_path: Path) -> None:
        """Save and reload preserves all state fields."""
        state = make_pipeline_state()
        state.config.run_id = "roundtrip-test"
        state.profile = make_candidate_profile()
        state.preferences = make_search_preferences()
        state.companies = [make_company(), make_company(name="Other Corp")]
        state.total_tokens = 1200
        state.total_cost_usd = 0.15

        checkpoint = state.to_checkpoint("find_companies")
        save_checkpoint(checkpoint, tmp_path)

        loaded = load_latest_checkpoint("roundtrip-test", tmp_path)
        assert loaded is not None

        restored = PipelineState.from_checkpoint(loaded)
        assert restored.config.run_id == "roundtrip-test"
        assert restored.profile is not None
        assert restored.profile.name == state.profile.name
        assert restored.preferences is not None
        assert len(restored.companies) == 2
        assert restored.total_tokens == 1200
        assert abs(restored.total_cost_usd - 0.15) < 0.001
