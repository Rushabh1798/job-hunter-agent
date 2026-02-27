"""Tests for observability/cost_tracker.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from job_hunter_agents.observability.cost_tracker import (
    CostTracker,
    LLMCallMetrics,
)
from job_hunter_core.exceptions import CostLimitExceededError


def _make_state(total_tokens: int = 0, total_cost_usd: float = 0.0) -> MagicMock:
    """Create a mock PipelineState."""
    state = MagicMock()
    state.total_tokens = total_tokens
    state.total_cost_usd = total_cost_usd
    return state


def _make_metrics(
    model: str = "claude-haiku-4-5-20251001",
    input_tokens: int = 100,
    output_tokens: int = 50,
    duration_seconds: float = 0.5,
    agent_name: str = "test_agent",
) -> LLMCallMetrics:
    """Create a test LLMCallMetrics."""
    return LLMCallMetrics(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_seconds=duration_seconds,
        agent_name=agent_name,
    )


@pytest.mark.unit
class TestCostTracker:
    """Tests for CostTracker."""

    def test_record_call_updates_state(self) -> None:
        """Record call increments state tokens and cost."""
        tracker = CostTracker()
        state = _make_state()
        metrics = _make_metrics(input_tokens=1000, output_tokens=500)

        tracker.record_call(metrics, state, max_cost=10.0, warn_threshold=5.0)

        assert state.total_tokens == 1500
        # Haiku pricing: 1000 * 0.80/1M + 500 * 4.00/1M = 0.0008 + 0.002 = 0.0028
        assert abs(state.total_cost_usd - 0.0028) < 1e-6

    def test_record_call_raises_on_cost_limit(self) -> None:
        """Raises CostLimitExceededError when cost exceeds max."""
        tracker = CostTracker()
        state = _make_state(total_cost_usd=0.0)
        metrics = _make_metrics(input_tokens=1_000_000, output_tokens=500_000)

        with pytest.raises(CostLimitExceededError):
            tracker.record_call(metrics, state, max_cost=0.001, warn_threshold=0.0001)

    def test_record_call_warns_on_threshold(self, caplog: pytest.LogCaptureFixture) -> None:
        """Logs warning when cost exceeds threshold but not limit."""
        tracker = CostTracker()
        state = _make_state()
        metrics = _make_metrics(input_tokens=100_000, output_tokens=50_000)

        # warn at 0.001, limit at 100.0 — should warn but not raise
        tracker.record_call(metrics, state, max_cost=100.0, warn_threshold=0.001)
        assert len(tracker.calls) == 1

    def test_record_call_unknown_model(self) -> None:
        """Unknown model: tokens tracked, cost stays 0."""
        tracker = CostTracker()
        state = _make_state()
        metrics = _make_metrics(model="unknown-model-v1", input_tokens=500, output_tokens=200)

        tracker.record_call(metrics, state, max_cost=10.0, warn_threshold=5.0)

        assert state.total_tokens == 700
        assert state.total_cost_usd == 0.0

    def test_summary_empty(self) -> None:
        """Empty tracker returns zeroed summary."""
        tracker = CostTracker()
        summary = tracker.summary()

        assert summary["total_calls"] == 0
        assert summary["total_tokens"] == 0
        assert summary["total_cost_usd"] == 0.0
        assert summary["cost_by_model"] == {}

    def test_summary_with_calls(self) -> None:
        """Summary aggregates across multiple calls."""
        tracker = CostTracker()
        tracker.calls = [
            _make_metrics(model="claude-haiku-4-5-20251001", input_tokens=1000, output_tokens=500),
            _make_metrics(
                model="claude-sonnet-4-5-20250514", input_tokens=2000, output_tokens=1000
            ),
        ]
        summary = tracker.summary()

        assert summary["total_calls"] == 2
        assert summary["total_tokens"] == 4500
        assert isinstance(summary["cost_by_model"], dict)
        assert len(summary["cost_by_model"]) == 2
        total_cost = summary["total_cost_usd"]
        assert isinstance(total_cost, float)
        assert total_cost > 0
