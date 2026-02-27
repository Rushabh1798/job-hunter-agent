"""Jobs scorer agent — scores normalized jobs against candidate profile."""

from __future__ import annotations

import re
import time

import structlog
from pydantic import BaseModel, Field

from job_hunter_agents.agents.base import BaseAgent
from job_hunter_agents.prompts.job_scorer import (
    JOB_SCORER_USER,
)
from job_hunter_core.models.candidate import CandidateProfile, SearchPreferences
from job_hunter_core.models.job import FitReport, NormalizedJob, ScoredJob
from job_hunter_core.state import PipelineState

logger = structlog.get_logger()

BATCH_SIZE = 5

# Regex to exclude clearly non-engineering roles (case-insensitive)
_EXCLUDED_TITLE_RE = re.compile(
    r"\baccount\s*(executive|manager)\b|\bsales\b|\brecruiter\b"
    r"|\baccountant\b|\baccounts?\s*(payable|receivable)\b"
    r"|\b(human\s*resources?|hr\s*(manager|generalist))\b"
    r"|\bmarketing\s*(manager|specialist|coordinator)\b"
    r"|\b(content\s*writer|copywriter|paralegal)\b"
    r"|\b(office\s*manager|administrative\s*assistant|receptionist)\b"
    r"|\bcustomer\s*(success|support)\b",
    re.IGNORECASE,
)

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

        # Pre-filter: relevance-rank, limit per company, cap total
        all_jobs = state.normalized_jobs
        jobs = self._relevance_prefilter(
            all_jobs,
            state.profile,
            state.preferences,
        )

        if len(jobs) < len(all_jobs):
            logger.info(
                "scorer_pre_filtered",
                original=len(all_jobs),
                filtered=len(jobs),
            )

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

        jobs_block = self._format_jobs_block(jobs, state=state)
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

    def _relevance_prefilter(
        self,
        jobs: list[NormalizedJob],
        profile: CandidateProfile | None,
        prefs: SearchPreferences | None,
    ) -> list[NormalizedJob]:
        """Rank jobs by title/skill relevance, exclude non-engineering roles."""
        # Build keyword set from profile and preferences
        keywords: set[str] = set()
        if profile:
            keywords.update(w.lower() for s in profile.skills for w in s.name.split() if len(w) > 2)
            if profile.current_title:
                keywords.update(w.lower() for w in profile.current_title.split() if len(w) > 2)
        if prefs:
            for title in prefs.target_titles:
                keywords.update(w.lower() for w in title.split() if len(w) > 2)

        # Build location keywords for matching (with common aliases)
        pref_locations: list[str] = []
        if prefs:
            pref_locations = [loc.lower() for loc in prefs.preferred_locations]
            # Expand Indian city aliases so "Bangalore" also matches "Bengaluru"
            india_aliases: dict[str, list[str]] = {
                "bangalore": ["bengaluru", "india"],
                "bengaluru": ["bangalore", "india"],
                "mumbai": ["bombay", "india"],
                "pune": ["india"],
                "hyderabad": ["india"],
                "chennai": ["madras", "india"],
                "noida": ["delhi", "ncr", "india"],
                "gurgaon": ["gurugram", "india"],
                "gurugram": ["gurgaon", "india"],
                "ahmedabad": ["india"],
            }
            expanded: set[str] = set(pref_locations)
            for loc in list(pref_locations):
                for alias_key, aliases in india_aliases.items():
                    if alias_key in loc:
                        expanded.update(aliases)
            pref_locations = list(expanded)

        # Score and filter
        scored: list[tuple[float, NormalizedJob]] = []
        for job in jobs:
            title_lower = job.title.lower()

            # Skip clearly non-engineering roles
            if _EXCLUDED_TITLE_RE.search(title_lower):
                continue

            # Hard location filter: exclude jobs in non-matching locations
            # Also exclude empty-location non-remote jobs when prefs are set
            job_loc = (job.location or "").lower()
            if pref_locations:
                if not job_loc and job.remote_type != "remote":
                    continue
                if job_loc:
                    loc_ok = any(pl in job_loc for pl in pref_locations)
                    if not loc_ok and job.remote_type != "remote":
                        continue

            # Relevance score: title keyword overlap + skill overlap
            title_words = set(title_lower.split())
            score = len(title_words & keywords) * 2.0
            job_skills = {s.lower() for s in job.required_skills}
            score += len(job_skills & keywords) * 1.0

            # Location bonus: strongly prefer matching locations
            for pref_loc in pref_locations:
                if pref_loc in job_loc:
                    score += 10.0
                    break
            if job.remote_type == "remote":
                score += 5.0

            scored.append((score, job))

        # Sort by relevance, then take top N per company
        scored.sort(key=lambda x: x[0], reverse=True)

        per_company: dict[str, int] = {}
        result: list[NormalizedJob] = []
        for _score, job in scored:
            company = job.company_name or "unknown"
            count = per_company.get(company, 0)
            if count >= self.settings.max_jobs_per_company:
                continue
            per_company[company] = count + 1
            result.append(job)
            if len(result) >= self.settings.top_k_semantic:
                break

        return result

    def _format_jobs_block(
        self,
        jobs: list[NormalizedJob],
        state: PipelineState | None = None,
    ) -> str:
        """Format jobs for the scoring prompt."""
        # Build company_id -> tier lookup
        tier_map: dict[str, str] = {}
        if state:
            for company in state.companies:
                tier_map[str(company.id)] = company.tier.value

        blocks: list[str] = []
        for i, job in enumerate(jobs):
            salary = "Not specified"
            if job.salary_min and job.salary_max:
                sym = _currency_symbol(job.currency or "USD")
                cur = job.currency or "USD"
                salary = f"{sym}{job.salary_min:,}-{sym}{job.salary_max:,} {cur}"

            tier = tier_map.get(str(job.company_id), "unknown")

            blocks.append(
                f'<job index="{i}">\n'
                f"Company: {job.company_name}\n"
                f"Company Tier: {tier}\n"
                f"Title: {job.title}\n"
                f"Location: {job.location or 'Not specified'}\n"
                f"Remote: {job.remote_type}\n"
                f"Posted Date: {job.posted_date or 'Unknown'}\n"
                f"Salary: {salary}\n"
                f"Required Skills: {', '.join(job.required_skills) or 'Not specified'}\n"
                f"Preferred Skills: {', '.join(job.preferred_skills) or 'None'}\n"
                f"Experience: {job.required_experience_years or 'Not specified'} years\n"
                f"Seniority: {job.seniority_level or 'Not specified'}\n"
                f"Description: {job.jd_text[:1000]}\n"
                f"</job>"
            )
        return "\n\n".join(blocks)
