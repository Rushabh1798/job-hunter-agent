"""Tests for BaseAgent LLM calling, cost tracking, and error recording."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from job_hunter_agents.agents.base import BaseAgent
from job_hunter_core.exceptions import CostLimitExceededError
from job_hunter_core.state import PipelineState
from tests.mocks.mock_factories import make_pipeline_state
from tests.mocks.mock_settings import make_settings


class _DummyResponse(BaseModel):
    """Trivial response model for testing."""

    answer: str


class _StubAgent(BaseAgent):
    """Concrete subclass for testing BaseAgent methods."""

    agent_name: str = "stub"

    async def run(self, state: PipelineState) -> PipelineState:
        """No-op run."""
        return state


def _create_stub_agent(**settings_overrides: object) -> _StubAgent:
    """Instantiate _StubAgent with patched AsyncAnthropic + instructor."""
    settings = make_settings(**settings_overrides)
    with (
        patch("job_hunter_agents.agents.base.AsyncAnthropic"),
        patch("job_hunter_agents.agents.base.instructor"),
    ):
        return _StubAgent(settings)


@pytest.mark.unit
class TestCallLLM:
    """Test _call_llm method."""

    @pytest.mark.asyncio
    async def test_call_llm_returns_response(self) -> None:
        """instructor.messages.create result is returned."""
        agent = _create_stub_agent()
        expected = _DummyResponse(answer="hello")
        agent._instructor.messages.create = AsyncMock(return_value=expected)

        with patch(
            "job_hunter_agents.agents.base.extract_token_usage",
            return_value=(10, 20),
        ):
            result = await agent._call_llm(
                messages=[{"role": "user", "content": "test"}],
                model="claude-haiku-4-5-20251001",
                response_model=_DummyResponse,
            )

        assert result.answer == "hello"

    @pytest.mark.asyncio
    async def test_call_llm_extracts_tokens(self) -> None:
        """extract_token_usage is called on the result."""
        agent = _create_stub_agent()
        response = _DummyResponse(answer="ok")
        agent._instructor.messages.create = AsyncMock(return_value=response)

        with patch(
            "job_hunter_agents.agents.base.extract_token_usage",
            return_value=(100, 200),
        ) as mock_extract:
            await agent._call_llm(
                messages=[{"role": "user", "content": "test"}],
                model="claude-haiku-4-5-20251001",
                response_model=_DummyResponse,
            )

        mock_extract.assert_called_once_with(response)

    @pytest.mark.asyncio
    async def test_call_llm_tracks_cost_with_state(self) -> None:
        """_track_cost is called when state is provided."""
        agent = _create_stub_agent()
        agent._instructor.messages.create = AsyncMock(return_value=_DummyResponse(answer="ok"))
        state = make_pipeline_state()

        with (
            patch(
                "job_hunter_agents.agents.base.extract_token_usage",
                return_value=(100, 50),
            ),
            patch.object(agent, "_track_cost") as mock_track,
        ):
            await agent._call_llm(
                messages=[{"role": "user", "content": "test"}],
                model="claude-haiku-4-5-20251001",
                response_model=_DummyResponse,
                state=state,
            )

        mock_track.assert_called_once_with(state, 100, 50, "claude-haiku-4-5-20251001")

    @pytest.mark.asyncio
    async def test_call_llm_no_tracking_without_state(self) -> None:
        """_track_cost is NOT called when state=None."""
        agent = _create_stub_agent()
        agent._instructor.messages.create = AsyncMock(return_value=_DummyResponse(answer="ok"))

        with (
            patch(
                "job_hunter_agents.agents.base.extract_token_usage",
                return_value=(10, 20),
            ),
            patch.object(agent, "_track_cost") as mock_track,
        ):
            await agent._call_llm(
                messages=[{"role": "user", "content": "test"}],
                model="claude-haiku-4-5-20251001",
                response_model=_DummyResponse,
                state=None,
            )

        mock_track.assert_not_called()


@pytest.mark.unit
class TestTrackCost:
    """Test _track_cost accumulation and guardrails."""

    def test_updates_state_tokens(self) -> None:
        """Tokens are accumulated correctly in state."""
        agent = _create_stub_agent()
        state = make_pipeline_state()

        agent._track_cost(state, 100, 200, "claude-haiku-4-5-20251001")

        assert state.total_tokens == 300

    def test_known_model_computes_cost(self) -> None:
        """Haiku model computes cost from TOKEN_PRICES."""
        agent = _create_stub_agent()
        state = make_pipeline_state()

        # haiku: input=$0.80/1M, output=$4.00/1M
        agent._track_cost(state, 1_000_000, 1_000_000, "claude-haiku-4-5-20251001")

        # 1M * 0.80/1M + 1M * 4.00/1M = 4.80
        assert state.total_cost_usd == pytest.approx(4.80)

    def test_unknown_model_no_cost(self) -> None:
        """Unknown model adds tokens but not cost."""
        agent = _create_stub_agent()
        state = make_pipeline_state()

        agent._track_cost(state, 500, 500, "unknown-model-xyz")

        assert state.total_tokens == 1000
        assert state.total_cost_usd == 0.0

    def test_exceeds_limit_raises(self) -> None:
        """CostLimitExceededError raised when cost exceeds max."""
        agent = _create_stub_agent(max_cost_per_run_usd=0.01)
        state = make_pipeline_state()

        with pytest.raises(CostLimitExceededError):
            agent._track_cost(state, 1_000_000, 1_000_000, "claude-haiku-4-5-20251001")

    def test_warn_threshold_logs(self) -> None:
        """Warning is emitted when cost exceeds warn threshold."""
        agent = _create_stub_agent(
            warn_cost_threshold_usd=0.001,
            max_cost_per_run_usd=100.0,
        )
        state = make_pipeline_state()

        with patch("job_hunter_agents.agents.base.logger") as mock_logger:
            agent._track_cost(state, 100_000, 100_000, "claude-haiku-4-5-20251001")

        mock_logger.warning.assert_called_once()


@pytest.mark.unit
class TestRecordError:
    """Test _record_error method."""

    def test_appends_agent_error(self) -> None:
        """State.errors grows by 1 after recording an error."""
        agent = _create_stub_agent()
        state = make_pipeline_state()
        assert len(state.errors) == 0

        agent._record_error(state, ValueError("boom"), is_fatal=False)

        assert len(state.errors) == 1
        assert state.errors[0].agent_name == "stub"
        assert state.errors[0].error_type == "ValueError"
        assert state.errors[0].error_message == "boom"
        assert state.errors[0].is_fatal is False
