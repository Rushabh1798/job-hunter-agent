"""Tests for checkpoint save/load I/O."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from job_hunter_agents.orchestrator.checkpoint import (
    load_latest_checkpoint,
    save_checkpoint,
)
from job_hunter_core.exceptions import CheckpointError
from job_hunter_core.models.run import PipelineCheckpoint


def _make_checkpoint(run_id: str = "test-run", step: str = "parse_resume") -> PipelineCheckpoint:
    """Create a PipelineCheckpoint with minimal state snapshot."""
    return PipelineCheckpoint(
        run_id=run_id,
        completed_step=step,
        state_snapshot={
            "config": {
                "run_id": run_id,
                "resume_path": "/tmp/r.pdf",
                "preferences_text": "test",
            },
        },
    )


@pytest.mark.unit
class TestSaveCheckpoint:
    """Test save_checkpoint file I/O."""

    def test_save_creates_file(self, tmp_path: Path) -> None:
        """Checkpoint is saved as {run_id}--{step}.json."""
        cp = _make_checkpoint(run_id="run-1", step="parse_resume")
        path = save_checkpoint(cp, tmp_path)

        assert path.exists()
        assert path.name == "run-1--parse_resume.json"

    def test_save_creates_missing_directory(self, tmp_path: Path) -> None:
        """parents=True creates intermediate directories."""
        nested = tmp_path / "a" / "b" / "c"
        cp = _make_checkpoint()
        path = save_checkpoint(cp, nested)

        assert path.exists()
        assert nested.is_dir()

    def test_save_content_valid_json(self, tmp_path: Path) -> None:
        """Saved file content deserializes to PipelineCheckpoint."""
        cp = _make_checkpoint(run_id="run-2", step="parse_prefs")
        path = save_checkpoint(cp, tmp_path)

        data = json.loads(path.read_text())
        restored = PipelineCheckpoint(**data)
        assert restored.run_id == "run-2"
        assert restored.completed_step == "parse_prefs"


@pytest.mark.unit
class TestLoadLatestCheckpoint:
    """Test load_latest_checkpoint file I/O."""

    def test_load_missing_dir_returns_none(self, tmp_path: Path) -> None:
        """Non-existent directory returns None."""
        result = load_latest_checkpoint("run-1", tmp_path / "does_not_exist")
        assert result is None

    def test_load_no_matching_run_returns_none(self, tmp_path: Path) -> None:
        """Directory exists but no files match the run_id."""
        cp = _make_checkpoint(run_id="other-run")
        save_checkpoint(cp, tmp_path)

        result = load_latest_checkpoint("run-1", tmp_path)
        assert result is None

    def test_load_picks_newest_by_mtime(self, tmp_path: Path) -> None:
        """When multiple checkpoints exist, the newest (by mtime) is returned."""
        cp1 = _make_checkpoint(run_id="run-1", step="step_a")
        save_checkpoint(cp1, tmp_path)
        time.sleep(0.05)  # ensure different mtime

        cp2 = _make_checkpoint(run_id="run-1", step="step_b")
        save_checkpoint(cp2, tmp_path)

        result = load_latest_checkpoint("run-1", tmp_path)
        assert result is not None
        assert result.completed_step == "step_b"

    def test_load_corrupt_json_raises(self, tmp_path: Path) -> None:
        """Invalid JSON in checkpoint file raises CheckpointError."""
        corrupt_file = tmp_path / "run-1--parse_resume.json"
        corrupt_file.write_text("{{{invalid json")

        with pytest.raises(CheckpointError):
            load_latest_checkpoint("run-1", tmp_path)
