"""Run configuration and result models."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RunConfig(BaseModel):
    """Configuration for a single pipeline run."""

    run_id: str = Field(
        default_factory=lambda: f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
        description="Unique run identifier",
    )
    resume_path: Path = Field(description="Path to the resume PDF file")
    preferences_text: str = Field(description="Freeform job preferences text")
    dry_run: bool = Field(default=False, description="Skip email, generate files only")
    force_rescrape: bool = Field(default=False, description="Ignore scrape cache")
    company_limit: int | None = Field(
        default=None, description="Cap number of companies for testing"
    )
    output_formats: list[str] = Field(
        default_factory=lambda: ["xlsx", "csv"], description="Output file formats (csv, xlsx)"
    )
    lite_mode: bool = Field(
        default=False, description="SQLite + local embeddings, no Docker"
    )


class AgentError(BaseModel):
    """Record of an error that occurred during agent execution."""

    agent_name: str = Field(description="Name of the agent that errored")
    error_type: str = Field(description="Exception class name")
    error_message: str = Field(description="Error description")
    company_name: str | None = Field(default=None, description="Related company if applicable")
    job_id: UUID | None = Field(default=None, description="Related job ID if applicable")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When the error occurred"
    )
    is_fatal: bool = Field(default=False, description="Whether this error stopped the pipeline")


class PipelineCheckpoint(BaseModel):
    """Serializable checkpoint for crash recovery."""

    run_id: str = Field(description="Run this checkpoint belongs to")
    completed_step: str = Field(description="Name of the last completed step")
    state_snapshot: dict[str, object] = Field(description="Serialized PipelineState")
    saved_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this checkpoint was saved"
    )


class RunResult(BaseModel):
    """Summary of a completed pipeline run."""

    run_id: str = Field(description="Run identifier")
    status: Literal["success", "partial", "failed"] = Field(description="Overall run status")
    companies_attempted: int = Field(description="Number of companies targeted")
    companies_succeeded: int = Field(description="Number of companies successfully scraped")
    jobs_scraped: int = Field(description="Total raw jobs collected")
    jobs_scored: int = Field(description="Total jobs scored")
    jobs_in_output: int = Field(description="Jobs included in final output")
    output_files: list[Path] = Field(description="Paths to generated output files")
    email_sent: bool = Field(description="Whether results were emailed")
    errors: list[AgentError] = Field(description="All errors encountered during run")
    total_tokens_used: int = Field(description="Total LLM tokens consumed")
    estimated_cost_usd: float = Field(description="Estimated total cost in USD")
    duration_seconds: float = Field(description="Total run duration in seconds")
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When the run completed"
    )
