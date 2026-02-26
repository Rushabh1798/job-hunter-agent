"""Pipeline state — mutable state passed through the pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from job_hunter_core.models.candidate import CandidateProfile, SearchPreferences
from job_hunter_core.models.company import Company
from job_hunter_core.models.job import NormalizedJob, RawJob, ScoredJob
from job_hunter_core.models.run import (
    AgentError,
    PipelineCheckpoint,
    RunConfig,
    RunResult,
)


@dataclass
class PipelineState:
    """Mutable state passed through the pipeline. Serializable to JSON for checkpoints."""

    config: RunConfig

    # Step outputs
    profile: CandidateProfile | None = None
    preferences: SearchPreferences | None = None
    companies: list[Company] = field(default_factory=list)
    raw_jobs: list[RawJob] = field(default_factory=list)
    normalized_jobs: list[NormalizedJob] = field(default_factory=list)
    scored_jobs: list[ScoredJob] = field(default_factory=list)

    # Cross-cutting
    errors: list[AgentError] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    run_result: RunResult | None = None

    def to_checkpoint(self, step_name: str) -> PipelineCheckpoint:
        """Serialize current state for crash recovery."""
        snapshot: dict[str, object] = {
            "config": json.loads(self.config.model_dump_json()),
            "profile": json.loads(self.profile.model_dump_json()) if self.profile else None,
            "preferences": (
                json.loads(self.preferences.model_dump_json()) if self.preferences else None
            ),
            "companies": [json.loads(c.model_dump_json()) for c in self.companies],
            "raw_jobs": [json.loads(j.model_dump_json()) for j in self.raw_jobs],
            "normalized_jobs": [json.loads(j.model_dump_json()) for j in self.normalized_jobs],
            "scored_jobs": [json.loads(j.model_dump_json()) for j in self.scored_jobs],
            "errors": [json.loads(e.model_dump_json()) for e in self.errors],
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "run_result": (
                json.loads(self.run_result.model_dump_json()) if self.run_result else None
            ),
        }
        return PipelineCheckpoint(
            run_id=self.config.run_id,
            completed_step=step_name,
            state_snapshot=snapshot,
        )

    @classmethod
    def from_checkpoint(cls, checkpoint: PipelineCheckpoint) -> PipelineState:
        """Restore state from a checkpoint file."""
        snap = checkpoint.state_snapshot
        config_data = snap.get("config")
        if not isinstance(config_data, dict):
            msg = "Invalid checkpoint: missing config"
            raise ValueError(msg)

        state = cls(config=RunConfig(**config_data))

        profile_data = snap.get("profile")
        if isinstance(profile_data, dict):
            state.profile = CandidateProfile(**profile_data)

        prefs_data = snap.get("preferences")
        if isinstance(prefs_data, dict):
            state.preferences = SearchPreferences(**prefs_data)

        companies_data = snap.get("companies")
        if isinstance(companies_data, list):
            state.companies = [Company(**c) for c in companies_data]

        raw_jobs_data = snap.get("raw_jobs")
        if isinstance(raw_jobs_data, list):
            state.raw_jobs = [RawJob(**j) for j in raw_jobs_data]

        normalized_data = snap.get("normalized_jobs")
        if isinstance(normalized_data, list):
            state.normalized_jobs = [NormalizedJob(**j) for j in normalized_data]

        scored_data = snap.get("scored_jobs")
        if isinstance(scored_data, list):
            state.scored_jobs = [ScoredJob(**j) for j in scored_data]

        errors_data = snap.get("errors")
        if isinstance(errors_data, list):
            state.errors = [AgentError(**e) for e in errors_data]

        tokens = snap.get("total_tokens")
        if isinstance(tokens, int):
            state.total_tokens = tokens

        cost = snap.get("total_cost_usd")
        if isinstance(cost, (int, float)):
            state.total_cost_usd = float(cost)

        run_result_data = snap.get("run_result")
        if isinstance(run_result_data, dict):
            state.run_result = RunResult(**run_result_data)

        return state

    @property
    def completed_steps(self) -> list[str]:
        """Infer which steps have been completed based on state contents."""
        steps: list[str] = []
        if self.profile is not None:
            steps.append("parse_resume")
        if self.preferences is not None:
            steps.append("parse_prefs")
        if self.companies:
            steps.append("find_companies")
        if self.raw_jobs:
            steps.append("scrape_jobs")
        if self.normalized_jobs:
            steps.append("process_jobs")
        if self.scored_jobs:
            steps.append("score_jobs")
        if self.run_result is not None:
            steps.append("aggregate")
        if self.run_result is not None and self.run_result.email_sent:
            steps.append("notify")
        return steps

    def build_result(
        self,
        status: str,
        duration_seconds: float,
        output_files: list[str] | None = None,
        email_sent: bool = False,
    ) -> RunResult:
        """Build a RunResult from current state."""
        from pathlib import Path

        companies_succeeded = len({j.company_id for j in self.raw_jobs})
        return RunResult(
            run_id=self.config.run_id,
            status=status,
            companies_attempted=len(self.companies),
            companies_succeeded=companies_succeeded,
            jobs_scraped=len(self.raw_jobs),
            jobs_scored=len(self.scored_jobs),
            jobs_in_output=len(self.scored_jobs),
            output_files=[Path(f) for f in (output_files or [])],
            email_sent=email_sent,
            errors=self.errors,
            total_tokens_used=self.total_tokens,
            estimated_cost_usd=self.total_cost_usd,
            duration_seconds=duration_seconds,
            completed_at=datetime.now(UTC),
        )
