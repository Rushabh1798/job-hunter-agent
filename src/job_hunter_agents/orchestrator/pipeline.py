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

            async with trace_pipeline_run(config.run_id):
                for step_name, agent_cls in PIPELINE_STEPS:
                    if step_name in state.completed_steps:
                        logger.info("step_skipped", step=step_name)
                        continue

                    try:
                        agent = agent_cls(self.settings)
                        state = await asyncio.wait_for(
                            agent.run(state),
                            timeout=self.settings.agent_timeout_seconds,
                        )

                        if self.settings.checkpoint_enabled:
                            checkpoint = state.to_checkpoint(step_name)
                            save_checkpoint(checkpoint, self.settings.checkpoint_dir)

                    except CostLimitExceededError as e:
                        logger.error("cost_limit_exceeded", error=str(e))
                        duration = time.monotonic() - start
                        self._log_cost_summary(state, duration)
                        return state.build_result(
                            status="partial",
                            duration_seconds=duration,
                        )

                    except FatalAgentError as e:
                        logger.error("fatal_agent_error", step=step_name, error=str(e))
                        duration = time.monotonic() - start
                        self._log_cost_summary(state, duration)
                        return state.build_result(
                            status="failed",
                            duration_seconds=duration,
                        )

                    except TimeoutError:
                        logger.error(
                            "agent_timeout",
                            step=step_name,
                            timeout=self.settings.agent_timeout_seconds,
                        )
                        duration = time.monotonic() - start
                        self._log_cost_summary(state, duration)
                        return state.build_result(
                            status="failed",
                            duration_seconds=duration,
                        )

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
