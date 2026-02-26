"""Pydantic models for Temporal workflow/activity inputs and outputs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WorkflowInput(BaseModel):
    """Input to start the JobHuntWorkflow."""

    run_id: str
    resume_path: str
    preferences_text: str
    dry_run: bool = False
    force_rescrape: bool = False
    company_limit: int | None = None
    lite_mode: bool = False
    output_formats: list[str] = Field(default_factory=lambda: ["xlsx", "csv"])
    # Task queue routing
    default_queue: str = "job-hunter-default"
    llm_queue: str = "job-hunter-llm"
    scraping_queue: str = "job-hunter-scraping"


class WorkflowOutput(BaseModel):
    """Output from the completed JobHuntWorkflow."""

    status: str
    companies_attempted: int = 0
    companies_succeeded: int = 0
    jobs_scraped: int = 0
    jobs_scored: int = 0
    jobs_in_output: int = 0
    output_files: list[str] = Field(default_factory=list)
    email_sent: bool = False
    total_tokens_used: int = 0
    estimated_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class StepInput(BaseModel):
    """Generic input for an agent step activity.

    Carries the full serialized PipelineState snapshot so
    the activity can reconstruct state, run the agent, and
    return the updated snapshot.
    """

    state_snapshot: dict[str, Any]


class StepResult(BaseModel):
    """Generic output from an agent step activity."""

    state_snapshot: dict[str, Any]
    tokens_used: int = 0
    cost_usd: float = 0.0


class ScrapeCompanyInput(BaseModel):
    """Input for the per-company scraping activity."""

    company_data: dict[str, Any]
    config_data: dict[str, Any]


class ScrapeCompanyResult(BaseModel):
    """Output from per-company scraping: list of raw jobs."""

    raw_jobs: list[dict[str, Any]] = Field(default_factory=list)
    tokens_used: int = 0
    cost_usd: float = 0.0
    errors: list[dict[str, Any]] = Field(default_factory=list)
