"""Base agent with LLM calling, cost tracking, and error recording."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypeVar

import instructor
import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from job_hunter_agents.observability.cost_tracker import extract_token_usage
from job_hunter_core.constants import TOKEN_PRICES
from job_hunter_core.exceptions import CostLimitExceededError
from job_hunter_core.models.run import AgentError
from job_hunter_core.state import PipelineState

if TYPE_CHECKING:
    from job_hunter_core.config.settings import Settings

T = TypeVar("T", bound=BaseModel)

logger = structlog.get_logger()


class BaseAgent(ABC):
    """Abstract base class for all pipeline agents."""

    agent_name: str = "base"

    def __init__(self, settings: Settings) -> None:
        """Initialize with settings."""
        self.settings = settings
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        self._instructor = instructor.from_anthropic(self._client)

    @abstractmethod
    async def run(self, state: PipelineState) -> PipelineState:
        """Execute the agent's task. Must be implemented by subclasses."""
        ...

    def _log_start(self, context: dict[str, object] | None = None) -> None:
        """Log agent execution start."""
        logger.info(
            "agent_start",
            agent=self.agent_name,
            **(context or {}),
        )

    def _log_end(
        self, duration: float, context: dict[str, object] | None = None
    ) -> None:
        """Log agent execution end with duration."""
        logger.info(
            "agent_end",
            agent=self.agent_name,
            duration_seconds=round(duration, 2),
            **(context or {}),
        )

    async def _call_llm(
        self,
        messages: list[dict[str, str]],
        model: str,
        response_model: type[T],
        max_retries: int = 3,
        state: PipelineState | None = None,
    ) -> T:
        """Call LLM with structured output via instructor.

        Tracks token usage and cost if state is provided.
        """

        @retry(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        )
        async def _do_call() -> T:
            response: T = await self._instructor.messages.create(
                model=model,
                max_tokens=4096,
                messages=messages,
                response_model=response_model,
            )
            return response

        start = time.monotonic()
        result = await _do_call()
        elapsed = time.monotonic() - start

        input_tokens, output_tokens = extract_token_usage(result)

        if state is not None:
            self._track_cost(state, input_tokens, output_tokens, model)

        logger.debug(
            "llm_call_complete",
            agent=self.agent_name,
            model=model,
            duration=round(elapsed, 2),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return result

    def _track_cost(
        self,
        state: PipelineState,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> None:
        """Track token usage and enforce cost guardrail."""
        state.total_tokens += input_tokens + output_tokens

        prices = TOKEN_PRICES.get(model)
        if prices:
            cost = (
                input_tokens * prices["input"] / 1_000_000
                + output_tokens * prices["output"] / 1_000_000
            )
            state.total_cost_usd += cost

        if state.total_cost_usd > self.settings.max_cost_per_run_usd:
            raise CostLimitExceededError(
                f"Run cost ${state.total_cost_usd:.2f} exceeds limit "
                f"${self.settings.max_cost_per_run_usd:.2f}"
            )

        if state.total_cost_usd > self.settings.warn_cost_threshold_usd:
            logger.warning(
                "cost_warning",
                current_cost=round(state.total_cost_usd, 3),
                limit=self.settings.max_cost_per_run_usd,
            )

    def _record_error(
        self,
        state: PipelineState,
        error: Exception,
        is_fatal: bool = False,
        company_name: str | None = None,
        job_id: str | None = None,
    ) -> None:
        """Record an error in the pipeline state."""
        agent_error = AgentError(
            agent_name=self.agent_name,
            error_type=type(error).__name__,
            error_message=str(error),
            company_name=company_name,
            job_id=job_id,
            is_fatal=is_fatal,
        )
        state.errors.append(agent_error)
        logger.error(
            "agent_error",
            agent=self.agent_name,
            error_type=type(error).__name__,
            error=str(error),
            is_fatal=is_fatal,
        )
