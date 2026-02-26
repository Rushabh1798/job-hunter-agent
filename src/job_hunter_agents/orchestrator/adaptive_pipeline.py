"""Adaptive pipeline — loops discovery steps until minimum job targets are met."""

from __future__ import annotations

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
from job_hunter_agents.orchestrator.pipeline import Pipeline
from job_hunter_core.models.job import ScoredJob
from job_hunter_core.models.run import RunConfig, RunResult
from job_hunter_core.state import PipelineState

if TYPE_CHECKING:
    from job_hunter_agents.agents.base import BaseAgent
    from job_hunter_core.config.settings import Settings

logger = structlog.get_logger()

# One-time setup steps (run once before the loop)
_SETUP_STEPS: list[tuple[str, type[BaseAgent]]] = [
    ("parse_resume", ResumeParserAgent),
    ("parse_prefs", PrefsParserAgent),
]

# Discovery steps (repeated in each iteration)
_DISCOVERY_STEPS: list[tuple[str, type[BaseAgent]]] = [
    ("find_companies", CompanyFinderAgent),
    ("scrape_jobs", JobsScraperAgent),
    ("process_jobs", JobProcessorAgent),
    ("score_jobs", JobsScorerAgent),
]

# Output steps (run once after the loop)
_OUTPUT_STEPS: list[tuple[str, type[BaseAgent]]] = [
    ("aggregate", AggregatorAgent),
    ("notify", NotifierAgent),
]


class AdaptivePipeline(Pipeline):
    """Pipeline that loops discovery steps until min_recommended_jobs is met."""

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings."""
        super().__init__(settings)

    async def run(self, config: RunConfig) -> RunResult:
        """Execute adaptive pipeline with discovery loop."""
        from job_hunter_agents.observability import (
            bind_run_context,
            clear_run_context,
            trace_pipeline_run,
        )

        start = time.monotonic()
        state = self._load_or_create_state(config)
        bind_run_context(config.run_id)

        try:
            logger.info("adaptive_pipeline_start", run_id=config.run_id)

            async with trace_pipeline_run(config.run_id) as root_span:
                # Phase 1: One-time setup
                for step_name, agent_cls in _SETUP_STEPS:
                    if step_name in state.completed_steps:
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

                # Phase 2: Adaptive discovery loop
                state = await self._discovery_loop(state, start)

                # Phase 3: One-time output
                for step_name, agent_cls in _OUTPUT_STEPS:
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

            return state.build_result(status="success", duration_seconds=duration)
        finally:
            clear_run_context()

    async def _discovery_loop(
        self,
        state: PipelineState,
        pipeline_start: float,
    ) -> PipelineState:
        """Run discovery steps in a loop until we have enough scored jobs."""
        min_jobs = self.settings.min_recommended_jobs
        max_iters = self.settings.max_discovery_iterations

        for iteration in range(max_iters):
            state.discovery_iteration = iteration

            # Snapshot existing scored jobs before this iteration
            prev_scored: list[ScoredJob] = list(state.scored_jobs)
            prev_hashes: set[str] = {sj.job.content_hash for sj in prev_scored}

            # Clear per-iteration working data
            state.companies = []
            state.raw_jobs = []
            state.normalized_jobs = []

            logger.info(
                "discovery_iteration_start",
                iteration=iteration,
                scored_so_far=len(prev_scored),
                target=min_jobs,
            )

            # Run discovery steps
            for step_name, agent_cls in _DISCOVERY_STEPS:
                result = await self._run_agent_step(
                    step_name,
                    agent_cls,
                    state,
                    pipeline_start,
                )
                if isinstance(result, RunResult):
                    # Fatal error — restore prev scored and return
                    state.scored_jobs = prev_scored
                    return state
                state = result

            # Merge: keep prev + add only new (deduplicate by content_hash)
            new_scored = [sj for sj in state.scored_jobs if sj.job.content_hash not in prev_hashes]
            merged = prev_scored + new_scored
            merged.sort(key=lambda s: s.fit_report.score, reverse=True)
            for rank, sj in enumerate(merged, start=1):
                sj.rank = rank
            state.scored_jobs = merged

            # Track attempted companies
            state.attempted_company_names.update(c.name for c in state.companies)

            logger.info(
                "discovery_iteration_end",
                iteration=iteration,
                new_jobs=len(new_scored),
                total_scored=len(state.scored_jobs),
            )

            if len(state.scored_jobs) >= min_jobs:
                logger.info(
                    "discovery_target_met",
                    scored=len(state.scored_jobs),
                    target=min_jobs,
                )
                break

        return state
