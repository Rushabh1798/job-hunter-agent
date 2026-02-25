"""Temporal activities wrapping existing agent .run() methods.

Each activity reconstructs the agent from settings (loaded from the worker's
environment), builds a minimal PipelineState from the input payload, calls the
agent's .run(), and extracts the relevant output.
"""

from __future__ import annotations

import json
from typing import Any

from temporalio import activity

from job_hunter_agents.orchestrator.temporal_payloads import (
    ScrapeCompanyInput,
    ScrapeCompanyResult,
    StepInput,
    StepResult,
)


def _get_settings() -> Any:  # noqa: ANN401
    """Load settings from worker environment (cached per process)."""
    from job_hunter_core.config.settings import Settings

    return Settings()  # type: ignore[call-arg]


def _state_from_snapshot(snapshot: dict[str, Any]) -> Any:  # noqa: ANN401
    """Reconstruct PipelineState from a checkpoint snapshot dict."""
    from job_hunter_core.models.run import PipelineCheckpoint
    from job_hunter_core.state import PipelineState

    checkpoint = PipelineCheckpoint(
        run_id=snapshot.get("config", {}).get("run_id", "unknown"),
        completed_step="",
        state_snapshot=snapshot,
    )
    return PipelineState.from_checkpoint(checkpoint)


def _state_to_snapshot(state: Any, step_name: str) -> dict[str, Any]:  # noqa: ANN401
    """Serialize PipelineState to a checkpoint snapshot dict."""
    checkpoint = state.to_checkpoint(step_name)
    return json.loads(checkpoint.model_dump_json())["state_snapshot"]


async def _run_agent_step(
    step_name: str, agent_cls_name: str, payload: StepInput,
) -> StepResult:
    """Common logic for running an agent step activity."""
    from job_hunter_agents.orchestrator.temporal_registry import AGENT_MAP

    settings = _get_settings()
    state = _state_from_snapshot(payload.state_snapshot)
    tokens_before = state.total_tokens
    cost_before = state.total_cost_usd

    agent_cls = AGENT_MAP[agent_cls_name]
    agent = agent_cls(settings)
    state = await agent.run(state)

    snapshot = _state_to_snapshot(state, step_name)
    return StepResult(
        state_snapshot=snapshot,
        tokens_used=state.total_tokens - tokens_before,
        cost_usd=state.total_cost_usd - cost_before,
    )


@activity.defn(name="parse_resume")
async def parse_resume_activity(payload: StepInput) -> StepResult:
    """Extract CandidateProfile from resume PDF."""
    return await _run_agent_step("parse_resume", "ResumeParserAgent", payload)


@activity.defn(name="parse_prefs")
async def parse_prefs_activity(payload: StepInput) -> StepResult:
    """Parse freeform preferences into SearchPreferences."""
    return await _run_agent_step("parse_prefs", "PrefsParserAgent", payload)


@activity.defn(name="find_companies")
async def find_companies_activity(payload: StepInput) -> StepResult:
    """Discover target companies via web search and LLM reasoning."""
    return await _run_agent_step("find_companies", "CompanyFinderAgent", payload)


@activity.defn(name="process_jobs")
async def process_jobs_activity(payload: StepInput) -> StepResult:
    """Normalize raw jobs and compute embeddings."""
    return await _run_agent_step("process_jobs", "JobProcessorAgent", payload)


@activity.defn(name="score_jobs")
async def score_jobs_activity(payload: StepInput) -> StepResult:
    """Score and rank normalized jobs against candidate profile."""
    return await _run_agent_step("score_jobs", "JobsScorerAgent", payload)


@activity.defn(name="aggregate")
async def aggregate_activity(payload: StepInput) -> StepResult:
    """Generate CSV/Excel output files."""
    return await _run_agent_step("aggregate", "AggregatorAgent", payload)


@activity.defn(name="notify")
async def notify_activity(payload: StepInput) -> StepResult:
    """Send email notification with results."""
    return await _run_agent_step("notify", "NotifierAgent", payload)


@activity.defn(name="scrape_company")
async def scrape_company_activity(payload: ScrapeCompanyInput) -> ScrapeCompanyResult:
    """Scrape jobs from a single company's career page."""
    from job_hunter_core.models.company import Company
    from job_hunter_core.models.run import RunConfig
    from job_hunter_core.state import PipelineState

    settings = _get_settings()
    company = Company(**payload.company_data)
    config = RunConfig(**payload.config_data)
    state = PipelineState(config=config, companies=[company])

    from job_hunter_agents.agents.jobs_scraper import JobsScraperAgent

    agent = JobsScraperAgent(settings)
    state = await agent.run(state)

    raw_jobs_dicts = [json.loads(j.model_dump_json()) for j in state.raw_jobs]
    error_dicts = [json.loads(e.model_dump_json()) for e in state.errors]
    return ScrapeCompanyResult(
        raw_jobs=raw_jobs_dicts,
        tokens_used=state.total_tokens,
        cost_usd=state.total_cost_usd,
        errors=error_dicts,
    )


ALL_ACTIVITIES = [
    parse_resume_activity,
    parse_prefs_activity,
    find_companies_activity,
    process_jobs_activity,
    score_jobs_activity,
    aggregate_activity,
    notify_activity,
    scrape_company_activity,
]
