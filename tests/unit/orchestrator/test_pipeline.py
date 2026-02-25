"""Tests for the sequential async pipeline orchestrator."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from job_hunter_agents.orchestrator.pipeline import Pipeline
from job_hunter_core.exceptions import CostLimitExceededError, FatalAgentError
from job_hunter_core.models.run import PipelineCheckpoint
from job_hunter_core.state import PipelineState
from tests.mocks.mock_factories import make_pipeline_state
from tests.mocks.mock_settings import make_settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockAgentA:
    """Mock agent that marks itself as having run."""

    def __init__(self, settings: object) -> None:
        self.settings = settings

    async def run(self, state: PipelineState) -> PipelineState:
        """Simulate step A completion."""
        state.total_tokens += 10
        return state


class _MockAgentB:
    """Mock agent that marks itself as having run."""

    def __init__(self, settings: object) -> None:
        self.settings = settings

    async def run(self, state: PipelineState) -> PipelineState:
        """Simulate step B completion."""
        state.total_tokens += 20
        return state


@asynccontextmanager
async def _noop_trace(run_id: str) -> AsyncIterator[None]:
    """No-op async context manager replacing trace_pipeline_run."""
    yield


MOCK_STEPS = [
    ("step_a", _MockAgentA),
    ("step_b", _MockAgentB),
]


def _enter_pipeline_patches(
    stack: ExitStack,
    steps: list[tuple[str, type[object]]] | None = None,
    checkpoint_return: object = None,
) -> dict[str, MagicMock]:
    """Enter all pipeline patches via an ExitStack. Returns named mocks."""
    mocks: dict[str, MagicMock] = {}
    mocks["steps"] = stack.enter_context(  # type: ignore[assignment]
        patch(
            "job_hunter_agents.orchestrator.pipeline.PIPELINE_STEPS",
            steps or MOCK_STEPS,
        )
    )
    stack.enter_context(
        patch(
            "job_hunter_agents.orchestrator.pipeline.trace_pipeline_run",
            side_effect=_noop_trace,
        )
    )
    mocks["bind"] = stack.enter_context(
        patch("job_hunter_agents.orchestrator.pipeline.bind_run_context")
    )
    mocks["clear"] = stack.enter_context(
        patch("job_hunter_agents.orchestrator.pipeline.clear_run_context")
    )
    mocks["save"] = stack.enter_context(
        patch("job_hunter_agents.orchestrator.pipeline.save_checkpoint")
    )
    mocks["load"] = stack.enter_context(
        patch(
            "job_hunter_agents.orchestrator.pipeline.load_latest_checkpoint",
            return_value=checkpoint_return,
        )
    )
    return mocks


def _make_error_steps(exc: Exception) -> list[tuple[str, type[object]]]:
    """Create a single-step pipeline that raises the given exception."""
    return [
        (
            "step_a",
            type(
                "_ErrorAgent",
                (),
                {
                    "__init__": lambda self, s: None,
                    "run": AsyncMock(side_effect=exc),
                },
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPipeline:
    """Test Pipeline.run orchestration."""

    @pytest.mark.asyncio
    async def test_run_success_all_steps(self) -> None:
        """All mock agents succeed -> status='success'."""
        settings = make_settings()
        pipeline = Pipeline(settings)

        with ExitStack() as stack:
            _enter_pipeline_patches(stack)
            result = await pipeline.run(make_pipeline_state().config)

        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_run_skips_completed_steps(self) -> None:
        """Agent for an already-completed step is not called."""
        settings = make_settings()
        pipeline = Pipeline(settings)

        call_log: list[str] = []

        class _TrackA:
            def __init__(self, s: object) -> None:
                pass

            async def run(self, state: PipelineState) -> PipelineState:
                call_log.append("parse_resume")
                return state

        class _TrackB:
            def __init__(self, s: object) -> None:
                pass

            async def run(self, state: PipelineState) -> PipelineState:
                call_log.append("step_b")
                return state

        tracking_steps = [("parse_resume", _TrackA), ("step_b", _TrackB)]

        # State with profile set -> completed_steps includes "parse_resume"
        state = make_pipeline_state()
        state.profile = MagicMock()

        with ExitStack() as stack:
            _enter_pipeline_patches(stack, steps=tracking_steps)
            stack.enter_context(patch.object(Pipeline, "_load_or_create_state", return_value=state))
            await pipeline.run(state.config)

        assert "parse_resume" not in call_log
        assert "step_b" in call_log

    @pytest.mark.asyncio
    async def test_run_cost_limit_returns_partial(self) -> None:
        """CostLimitExceededError -> status='partial'."""
        settings = make_settings()
        pipeline = Pipeline(settings)
        steps = _make_error_steps(CostLimitExceededError("over budget"))

        with ExitStack() as stack:
            _enter_pipeline_patches(stack, steps=steps)
            result = await pipeline.run(make_pipeline_state().config)

        assert result.status == "partial"

    @pytest.mark.asyncio
    async def test_run_fatal_error_returns_failed(self) -> None:
        """FatalAgentError -> status='failed'."""
        settings = make_settings()
        pipeline = Pipeline(settings)
        steps = _make_error_steps(FatalAgentError("unrecoverable"))

        with ExitStack() as stack:
            _enter_pipeline_patches(stack, steps=steps)
            result = await pipeline.run(make_pipeline_state().config)

        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_run_timeout_returns_failed(self) -> None:
        """TimeoutError -> status='failed'."""
        settings = make_settings(agent_timeout_seconds=0.001)
        pipeline = Pipeline(settings)
        steps = _make_error_steps(TimeoutError())

        with ExitStack() as stack:
            _enter_pipeline_patches(stack, steps=steps)
            result = await pipeline.run(make_pipeline_state().config)

        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_run_saves_checkpoints(self) -> None:
        """checkpoint_enabled=True -> save_checkpoint called per step."""
        settings = make_settings(checkpoint_enabled=True)
        pipeline = Pipeline(settings)

        with ExitStack() as stack:
            mocks = _enter_pipeline_patches(stack)
            await pipeline.run(make_pipeline_state().config)

        assert mocks["save"].call_count == 2

    @pytest.mark.asyncio
    async def test_run_no_checkpoints_when_disabled(self) -> None:
        """checkpoint_enabled=False -> save_checkpoint never called."""
        settings = make_settings(checkpoint_enabled=False)
        pipeline = Pipeline(settings)

        with ExitStack() as stack:
            mocks = _enter_pipeline_patches(stack)
            await pipeline.run(make_pipeline_state().config)

        mocks["save"].assert_not_called()

    @pytest.mark.asyncio
    async def test_run_binds_and_clears_context(self) -> None:
        """bind_run_context at start, clear_run_context in finally."""
        settings = make_settings()
        pipeline = Pipeline(settings)
        config = make_pipeline_state().config

        with ExitStack() as stack:
            mocks = _enter_pipeline_patches(stack)
            await pipeline.run(config)

        mocks["bind"].assert_called_once_with(config.run_id)
        mocks["clear"].assert_called_once()

    def test_load_or_create_fresh(self) -> None:
        """No checkpoint -> fresh PipelineState."""
        settings = make_settings(checkpoint_enabled=True)
        pipeline = Pipeline(settings)
        config = make_pipeline_state().config

        with patch(
            "job_hunter_agents.orchestrator.pipeline.load_latest_checkpoint",
            return_value=None,
        ):
            state = pipeline._load_or_create_state(config)

        assert state.config.run_id == config.run_id
        assert state.profile is None

    def test_load_or_create_from_checkpoint(self) -> None:
        """Checkpoint exists -> restored state."""
        settings = make_settings(checkpoint_enabled=True)
        pipeline = Pipeline(settings)
        config = make_pipeline_state().config

        cp = PipelineCheckpoint(
            run_id=config.run_id,
            completed_step="parse_resume",
            state_snapshot={
                "config": {
                    "run_id": config.run_id,
                    "resume_path": str(config.resume_path),
                    "preferences_text": config.preferences_text,
                },
                "total_tokens": 500,
                "total_cost_usd": 0.02,
            },
        )

        with patch(
            "job_hunter_agents.orchestrator.pipeline.load_latest_checkpoint",
            return_value=cp,
        ):
            state = pipeline._load_or_create_state(config)

        assert state.total_tokens == 500
        assert state.total_cost_usd == pytest.approx(0.02)
