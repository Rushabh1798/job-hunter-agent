"""Base agent with LLM calling, cost tracking, and error recording."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypeVar

import structlog
from llm_gateway import GatewayConfig, LLMClient  # type: ignore[import-untyped]
from llm_gateway.types import TokenUsage  # type: ignore[import-untyped]
from pydantic import BaseModel

from job_hunter_agents.observability import get_tracer
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

    def __init__(self, settings: Settings, llm_client: LLMClient | None = None) -> None:
        """Initialize with settings and optional pre-built LLM client."""
        self.settings = settings
        self._llm_client: LLMClient = llm_client or self._build_llm_client()

    def _build_llm_client(self) -> LLMClient:
        """Build LLM client from settings. Patch target for dry-run."""
        api_key = (
            self.settings.anthropic_api_key.get_secret_value()
            if self.settings.anthropic_api_key
            else None
        )
        config = GatewayConfig(
            provider=self.settings.llm_provider,
            api_key=api_key,
            max_retries=3,
            timeout_seconds=self.settings.llm_timeout_seconds,
            cost_limit_usd=None,
            cost_warn_usd=None,
            trace_enabled=False,
            log_level=self.settings.log_level,
            log_format=self.settings.log_format,
        )
        return LLMClient(config=config)

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

    def _log_end(self, duration: float, context: dict[str, object] | None = None) -> None:
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
        """Call LLM with structured output via llm-gateway.

        Retries are handled internally by the gateway provider.
        Tracks token usage and cost if state is provided.
        """
        tracer = get_tracer()
        span = tracer.start_span(f"llm.{self.agent_name}") if tracer else None

        start = time.monotonic()
        response = await self._llm_client.complete(
            messages=messages,
            response_model=response_model,
            model=model,
            max_tokens=4096,
        )
        elapsed = time.monotonic() - start

        usage = response.usage

        if state is not None:
            self._track_cost(state, usage)

        if span is not None:
            span.set_attribute("llm.model", model)
            span.set_attribute("llm.input_tokens", usage.input_tokens)
            span.set_attribute("llm.output_tokens", usage.output_tokens)
            span.set_attribute("llm.duration_seconds", round(elapsed, 3))
            span.set_attribute("llm.agent", self.agent_name)
            span.end()

        logger.debug(
            "llm_call_complete",
            agent=self.agent_name,
            model=model,
            duration=round(elapsed, 2),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        result: T = response.content  # type: ignore[assignment]
        return result

    def _track_cost(self, state: PipelineState, usage: TokenUsage) -> None:
        """Track token usage and enforce cost guardrail."""
        state.total_tokens += usage.total_tokens
        state.total_cost_usd += usage.total_cost_usd

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

    async def close(self) -> None:
        """Clean up LLM client resources."""
        await self._llm_client.close()

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
