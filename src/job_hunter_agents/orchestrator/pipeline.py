"""Sequential async pipeline with checkpoint-based crash recovery."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

from job_hunter_agents.agents.aggregator import AggregatorAgent
from job_hunter_agents.agents.company_finder import CompanyFinderAgent
from job_hunter_agents.agents.job_processor import JobProcessorAgent
from job_hunter_agents.agents.jobs_scorer import JobsScorerAgent
from job_hunter_agents.agents.jobs_scraper import JobsScraperAgent
from job_hunter_agents.agents.notifier import NotifierAgent
from job_hunter_agents.agents.prefs_parser import PrefsParserAgent
from job_hunter_agents.agents.resume_parser import ResumeParserAgent
from job_hunter_agents.observability import (
    bind_run_context,
    clear_run_context,
    get_tracer,
    trace_pipeline_run,
)
from job_hunter_agents.orchestrator.checkpoint import (
    load_latest_checkpoint,
    save_checkpoint,
)
from job_hunter_core.exceptions import CostLimitExceededError, FatalAgentError
from job_hunter_core.models.run import RunConfig, RunResult
from job_hunter_core.state import PipelineState

if TYPE_CHECKING:
    from job_hunter_agents.agents.base import BaseAgent
    from job_hunter_core.config.settings import Settings

logger = structlog.get_logger()

PIPELINE_STEPS: list[tuple[str, type[BaseAgent]]] = [
    ("parse_resume", ResumeParserAgent),
    ("parse_prefs", PrefsParserAgent),
    ("find_companies", CompanyFinderAgent),
    ("scrape_jobs", JobsScraperAgent),
    ("process_jobs", JobProcessorAgent),
    ("score_jobs", JobsScorerAgent),
    ("aggregate", AggregatorAgent),
    ("notify", NotifierAgent),
]


class Pipeline:
    """Sequential async pipeline with crash recovery via checkpoint files."""

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings."""
        self.settings = settings

    async def run(self, config: RunConfig) -> RunResult:
        """Execute the full pipeline."""
        start = time.monotonic()
        state = self._load_or_create_state(config)
        bind_run_context(config.run_id)

        try:
            logger.info("pipeline_start", run_id=config.run_id)

            async with trace_pipeline_run(config.run_id) as root_span:
                for step_name, agent_cls in PIPELINE_STEPS:
                    if step_name in state.completed_steps:
                        logger.info("step_skipped", step=step_name)
                        continue

                    result = await self._run_agent_step(
                        step_name,
                        agent_cls,
                        state,
                        start,
                    )
                    if isinstance(result, RunResult):
                        return result
                    state = result

                self._set_root_span_attrs(root_span, "success", state)

            duration = time.monotonic() - start
            self._log_cost_summary(state, duration)

            if state.run_result:
                state.run_result.duration_seconds = duration
                return state.run_result

            return state.build_result(
                status="success",
                duration_seconds=duration,
            )
        finally:
            clear_run_context()

    async def _run_agent_step(
        self,
        step_name: str,
        agent_cls: type[BaseAgent],
        state: PipelineState,
        pipeline_start: float,
    ) -> PipelineState | RunResult:
        """Execute a single agent step, optionally wrapped in a trace span."""
        tracer = get_tracer()
        span = None
        if tracer is not None:
            span = tracer.start_span(f"agent.{step_name}")
            span.set_attribute("agent.name", step_name)

        try:
            agent = agent_cls(self.settings)
            state = await asyncio.wait_for(
                agent.run(state),
                timeout=self.settings.agent_timeout_seconds,
            )

            if self.settings.checkpoint_enabled:
                checkpoint = state.to_checkpoint(step_name)
                save_checkpoint(checkpoint, self.settings.checkpoint_dir)

            if span is not None:
                span.set_attribute("agent.status", "ok")
                span.set_attribute("agent.tokens", state.total_tokens)

            return state

        except CostLimitExceededError as e:
            logger.error("cost_limit_exceeded", error=str(e))
            if span is not None:
                span.set_attribute("agent.status", "error")
                span.set_attribute("agent.error", str(e))
            duration = time.monotonic() - pipeline_start
            self._log_cost_summary(state, duration)
            return state.build_result(status="partial", duration_seconds=duration)

        except FatalAgentError as e:
            logger.error("fatal_agent_error", step=step_name, error=str(e))
            if span is not None:
                span.set_attribute("agent.status", "error")
                span.set_attribute("agent.error", str(e))
            duration = time.monotonic() - pipeline_start
            self._log_cost_summary(state, duration)
            return state.build_result(status="failed", duration_seconds=duration)

        except TimeoutError:
            logger.error(
                "agent_timeout",
                step=step_name,
                timeout=self.settings.agent_timeout_seconds,
            )
            if span is not None:
                span.set_attribute("agent.status", "error")
                span.set_attribute("agent.error", "timeout")
            duration = time.monotonic() - pipeline_start
            self._log_cost_summary(state, duration)
            return state.build_result(status="failed", duration_seconds=duration)

        finally:
            if span is not None:
                span.end()

    @staticmethod
    def _set_root_span_attrs(
        root_span: object | None,
        status: str,
        state: PipelineState,
    ) -> None:
        """Set summary attributes on the root pipeline span."""
        if root_span is None:
            return
        root_span.set_attribute("pipeline.status", status)  # type: ignore[attr-defined]
        root_span.set_attribute("pipeline.total_tokens", state.total_tokens)  # type: ignore[attr-defined]
        root_span.set_attribute(  # type: ignore[attr-defined]
            "pipeline.total_cost_usd",
            round(state.total_cost_usd, 4),
        )
        root_span.set_attribute("pipeline.jobs_scored", len(state.scored_jobs))  # type: ignore[attr-defined]
        root_span.set_attribute("pipeline.errors", len(state.errors))  # type: ignore[attr-defined]

    @staticmethod
    def _log_cost_summary(state: PipelineState, duration: float) -> None:
        """Log a structured cost and performance summary."""
        logger.info(
            "pipeline_summary",
            total_tokens=state.total_tokens,
            total_cost_usd=round(state.total_cost_usd, 4),
            duration_seconds=round(duration, 2),
            jobs_scored=len(state.scored_jobs),
            errors=len(state.errors),
        )

    def _load_or_create_state(self, config: RunConfig) -> PipelineState:
        """Load from checkpoint if available, otherwise create fresh state."""
        if self.settings.checkpoint_enabled:
            checkpoint = load_latest_checkpoint(config.run_id, self.settings.checkpoint_dir)
            if checkpoint:
                logger.info(
                    "resuming_from_checkpoint",
                    step=checkpoint.completed_step,
                )
                return PipelineState.from_checkpoint(checkpoint)

        return PipelineState(config=config)
