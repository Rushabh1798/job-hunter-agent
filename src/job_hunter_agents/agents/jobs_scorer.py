"""Jobs scorer agent — scores normalized jobs against candidate profile."""

from __future__ import annotations

import time

import structlog
from pydantic import BaseModel, Field

from job_hunter_agents.agents.base import BaseAgent
from job_hunter_agents.prompts.job_scorer import (
    JOB_SCORER_USER,
)
from job_hunter_core.models.job import FitReport, NormalizedJob, ScoredJob
from job_hunter_core.state import PipelineState

logger = structlog.get_logger()

BATCH_SIZE = 5

_CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "INR": "₹",
    "EUR": "€",
    "GBP": "£",
    "CAD": "C$",
    "AUD": "A$",
    "SGD": "S$",
}


def _currency_symbol(currency: str) -> str:
    """Return the symbol for a currency code, or the code itself as prefix."""
    return _CURRENCY_SYMBOLS.get(currency.upper(), f"{currency} ")


class JobScore(BaseModel):
    """Single job scoring result from LLM."""

    job_index: int = Field(description="Index of the job in the batch")
    score: int = Field(ge=0, le=100, description="Overall fit score")
    skill_overlap: list[str] = Field(default_factory=list)
    skill_gaps: list[str] = Field(default_factory=list)
    seniority_match: bool = Field(default=True)
    location_match: bool = Field(default=True)
    org_type_match: bool = Field(default=True)
    summary: str = Field(description="Fit summary")
    recommendation: str = Field(description="Recommendation category")
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)


class BatchScoreResult(BaseModel):
    """Batch scoring result from LLM."""

    scores: list[JobScore] = Field(description="Scores for each job in batch")


class JobsScorerAgent(BaseAgent):
    """Score normalized jobs against candidate profile using LLM."""

    agent_name = "jobs_scorer"

    async def run(self, state: PipelineState) -> PipelineState:
        """Score all normalized jobs in batches."""
        self._log_start({"jobs_count": len(state.normalized_jobs)})
        start = time.monotonic()

        if state.profile is None or state.preferences is None:
            logger.warning("scorer_missing_profile_or_prefs")
            return state

        jobs = state.normalized_jobs
        scored: list[ScoredJob] = []

        # Process in batches
        for i in range(0, len(jobs), BATCH_SIZE):
            batch = jobs[i : i + BATCH_SIZE]
            try:
                batch_scored = await self._score_batch(batch, state)
                scored.extend(batch_scored)
            except Exception as e:
                self._record_error(state, e)

        # Sort by score, filter by threshold, assign ranks
        scored.sort(key=lambda s: s.fit_report.score, reverse=True)
        filtered = [s for s in scored if s.fit_report.score >= self.settings.min_score_threshold]
        for rank, sj in enumerate(filtered, start=1):
            sj.rank = rank

        state.scored_jobs = filtered
        self._log_end(
            time.monotonic() - start,
            {
                "scored_count": len(scored),
                "above_threshold": len(filtered),
            },
        )
        return state

    async def _score_batch(
        self,
        jobs: list[NormalizedJob],
        state: PipelineState,
    ) -> list[ScoredJob]:
        """Score a batch of jobs via LLM."""
        profile = state.profile
        prefs = state.preferences
        assert profile is not None
        assert prefs is not None

        jobs_block = self._format_jobs_block(jobs)
        currency = prefs.currency or "USD"
        symbol = _currency_symbol(currency)
        salary_range = "Not specified"
        if prefs.min_salary and prefs.max_salary:
            salary_range = f"{symbol}{prefs.min_salary:,}-{symbol}{prefs.max_salary:,} {currency}"
        elif prefs.min_salary:
            salary_range = f"{symbol}{prefs.min_salary:,}+ {currency}"

        result = await self._call_llm(
            messages=[
                {
                    "role": "user",
                    "content": JOB_SCORER_USER.format(
                        name=profile.name,
                        current_title=profile.current_title or "Not specified",
                        years_of_experience=profile.years_of_experience,
                        seniority_level=profile.seniority_level or "Not specified",
                        skills=", ".join(s.name for s in profile.skills),
                        industries=", ".join(profile.industries) or "Not specified",
                        location=profile.location or "Not specified",
                        remote_preference=prefs.remote_preference,
                        org_types=", ".join(prefs.org_types),
                        salary_range=salary_range,
                        jobs_block=jobs_block,
                    ),
                },
            ],
            model=self.settings.sonnet_model,
            response_model=BatchScoreResult,
            state=state,
        )

        scored_jobs: list[ScoredJob] = []
        for score_result in result.scores:
            idx = score_result.job_index
            if 0 <= idx < len(jobs):
                rec = score_result.recommendation
                if rec not in ("strong_match", "good_match", "stretch", "mismatch"):
                    rec = "stretch"

                fit_report = FitReport(
                    score=score_result.score,
                    skill_overlap=score_result.skill_overlap,
                    skill_gaps=score_result.skill_gaps,
                    seniority_match=score_result.seniority_match,
                    location_match=score_result.location_match,
                    org_type_match=score_result.org_type_match,
                    summary=score_result.summary,
                    recommendation=rec,
                    confidence=score_result.confidence,
                )
                scored_jobs.append(ScoredJob(job=jobs[idx], fit_report=fit_report))

        return scored_jobs

    def _format_jobs_block(self, jobs: list[NormalizedJob]) -> str:
        """Format jobs for the scoring prompt."""
        blocks: list[str] = []
        for i, job in enumerate(jobs):
            salary = "Not specified"
            if job.salary_min and job.salary_max:
                sym = _currency_symbol(job.currency or "USD")
                cur = job.currency or "USD"
                salary = f"{sym}{job.salary_min:,}-{sym}{job.salary_max:,} {cur}"

            blocks.append(
                f'<job index="{i}">\n'
                f"Company: {job.company_name}\n"
                f"Title: {job.title}\n"
                f"Location: {job.location or 'Not specified'}\n"
                f"Remote: {job.remote_type}\n"
                f"Salary: {salary}\n"
                f"Required Skills: {', '.join(job.required_skills) or 'Not specified'}\n"
                f"Preferred Skills: {', '.join(job.preferred_skills) or 'None'}\n"
                f"Experience: {job.required_experience_years or 'Not specified'} years\n"
                f"Seniority: {job.seniority_level or 'Not specified'}\n"
                f"Description: {job.jd_text[:1000]}\n"
                f"</job>"
            )
        return "\n\n".join(blocks)
