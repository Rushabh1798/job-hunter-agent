"""LLM cost tracking and token usage extraction."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from llm_gateway.cost import calculate_cost  # type: ignore[import-untyped]

from job_hunter_core.exceptions import CostLimitExceededError
from job_hunter_core.state import PipelineState

logger = structlog.get_logger()


@dataclass
class LLMCallMetrics:
    """Metrics for a single LLM call."""

    model: str
    input_tokens: int
    output_tokens: int
    duration_seconds: float
    agent_name: str


@dataclass
class CostTracker:
    """Accumulates LLM call metrics and enforces cost guardrails."""

    calls: list[LLMCallMetrics] = field(default_factory=list)

    def record_call(
        self,
        metrics: LLMCallMetrics,
        state: PipelineState,
        max_cost: float,
        warn_threshold: float,
    ) -> None:
        """Record a call, update state, and enforce cost limits.

        Raises CostLimitExceededError if accumulated cost exceeds max_cost.
        Logs a warning when cost exceeds warn_threshold.
        """
        self.calls.append(metrics)
        total_tokens = metrics.input_tokens + metrics.output_tokens
        state.total_tokens += total_tokens

        input_cost, output_cost = calculate_cost(
            metrics.model, metrics.input_tokens, metrics.output_tokens
        )
        cost = input_cost + output_cost
        state.total_cost_usd += cost

        if state.total_cost_usd > max_cost:
            raise CostLimitExceededError(
                f"Run cost ${state.total_cost_usd:.4f} exceeds limit ${max_cost:.2f}"
            )

        if state.total_cost_usd > warn_threshold:
            logger.warning(
                "cost_warning",
                current_cost=round(state.total_cost_usd, 4),
                threshold=warn_threshold,
                limit=max_cost,
            )

    def summary(self) -> dict[str, object]:
        """Return aggregated cost summary for structured logging."""
        if not self.calls:
            return {
                "total_calls": 0,
                "total_tokens": 0,
                "cost_by_model": {},
                "total_cost_usd": 0.0,
            }

        total_tokens = 0
        cost_by_model: dict[str, float] = {}

        for call in self.calls:
            tokens = call.input_tokens + call.output_tokens
            total_tokens += tokens

            input_cost, output_cost = calculate_cost(
                call.model, call.input_tokens, call.output_tokens
            )
            cost = input_cost + output_cost
            if cost > 0:
                cost_by_model[call.model] = cost_by_model.get(call.model, 0.0) + cost

        total_cost = sum(cost_by_model.values())

        return {
            "total_calls": len(self.calls),
            "total_tokens": total_tokens,
            "cost_by_model": cost_by_model,
            "total_cost_usd": round(total_cost, 6),
        }
