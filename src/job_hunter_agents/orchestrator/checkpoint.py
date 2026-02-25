"""Checkpoint serialization and deserialization for crash recovery."""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from job_hunter_core.exceptions import CheckpointError
from job_hunter_core.models.run import PipelineCheckpoint

logger = structlog.get_logger()


def save_checkpoint(checkpoint: PipelineCheckpoint, checkpoint_dir: Path) -> Path:
    """Save checkpoint to JSON file."""
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{checkpoint.run_id}--{checkpoint.completed_step}.json"
    path = checkpoint_dir / filename

    try:
        path.write_text(checkpoint.model_dump_json(indent=2))
        logger.info(
            "checkpoint_saved",
            path=str(path),
            step=checkpoint.completed_step,
        )
        return path
    except OSError as e:
        msg = f"Failed to save checkpoint: {e}"
        raise CheckpointError(msg) from e


def load_latest_checkpoint(run_id: str, checkpoint_dir: Path) -> PipelineCheckpoint | None:
    """Load the most recent checkpoint for a given run ID."""
    if not checkpoint_dir.exists():
        return None

    matching = sorted(
        checkpoint_dir.glob(f"{run_id}--*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not matching:
        return None

    latest_path = matching[0]
    try:
        data = json.loads(latest_path.read_text())
        checkpoint = PipelineCheckpoint(**data)
        logger.info(
            "checkpoint_loaded",
            path=str(latest_path),
            step=checkpoint.completed_step,
        )
        return checkpoint
    except (json.JSONDecodeError, OSError) as e:
        msg = f"Failed to load checkpoint {latest_path}: {e}"
        raise CheckpointError(msg) from e
