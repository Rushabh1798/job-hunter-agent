"""Job processor agent — normalizes raw jobs into structured NormalizedJob."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, date, datetime

import structlog
from pydantic import BaseModel, Field

from job_hunter_agents.agents.base import BaseAgent
from job_hunter_agents.prompts.job_processor import (
    JOB_PROCESSOR_USER,
)
from job_hunter_core.models.job import NormalizedJob, RawJob
from job_hunter_core.state import PipelineState

logger = structlog.get_logger()


class ExtractedJob(BaseModel):
    """LLM-extracted job fields from raw content."""

    title: str = Field(description="Job title")
    jd_text: str = Field(description="Full job description")
    is_valid_posting: bool = Field(
        default=True,
        description=(
            "True if this is a specific job posting with one title and description. "
            "False if it is a career landing page, company overview, or list of many jobs."
        ),
    )
    location: str | None = Field(default=None, description="Location")
    remote_type: str = Field(default="unknown", description="Remote type")
    salary_min: int | None = Field(default=None, description="Min salary")
    salary_max: int | None = Field(default=None, description="Max salary")
    currency: str | None = Field(default=None, description="Salary currency")
    posted_date: str | None = Field(
        default=None, description="Job posting date if found (YYYY-MM-DD)"
    )
    apply_url: str | None = Field(
        default=None, description="Direct application URL if found in the content"
    )
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    required_experience_years: float | None = Field(default=None)
    seniority_level: str | None = Field(default=None)
    department: str | None = Field(default=None)


_REMOTE_TYPE_MAP: dict[str, str] = {
    "onsite": "onsite",
    "on-site": "onsite",
    "on_site": "onsite",
    "in-office": "onsite",
    "in_office": "onsite",
    "office": "onsite",
    "hybrid": "hybrid",
    "remote": "remote",
    "fully remote": "remote",
    "fully_remote": "remote",
    "work from home": "remote",
    "wfh": "remote",
    "unknown": "unknown",
}


def _normalize_remote_type(raw: str) -> str:
    """Normalize LLM-extracted remote_type to valid NormalizedJob enum value."""
    return _REMOTE_TYPE_MAP.get(raw.lower().strip(), "unknown")


class JobProcessorAgent(BaseAgent):
    """Normalize raw job data into structured NormalizedJob records."""

    agent_name = "job_processor"

    async def run(self, state: PipelineState) -> PipelineState:
        """Process all raw jobs into normalized jobs."""
        self._log_start({"raw_jobs_count": len(state.raw_jobs)})
        start = time.monotonic()

        seen_hashes: set[str] = set()

        for raw_job in state.raw_jobs:
            try:
                normalized = await self._process_job(raw_job)
                if normalized and normalized.content_hash not in seen_hashes:
                    seen_hashes.add(normalized.content_hash)
                    state.normalized_jobs.append(normalized)
            except Exception as e:
                self._record_error(
                    state,
                    e,
                    company_name=raw_job.company_name,
                    job_id=str(raw_job.id),
                )

        self._log_end(
            time.monotonic() - start,
            {
                "normalized_count": len(state.normalized_jobs),
            },
        )
        return state

    async def _process_job(self, raw_job: RawJob) -> NormalizedJob | None:
        """Process a single raw job into a normalized job."""
        if raw_job.raw_json:
            return self._process_from_json(raw_job)
        if raw_job.raw_html:
            return await self._process_from_html(raw_job)
        return None

    def _process_from_json(self, raw_job: RawJob) -> NormalizedJob | None:
        """Direct field mapping from ATS JSON — no LLM needed."""
        data = raw_job.raw_json
        if not data:
            return None

        title = str(data.get("title", ""))
        if not title:
            return None
        jd_text = str(data.get("content", data.get("description", "")))

        loc_data = data.get("location")
        location = ""
        if isinstance(loc_data, dict):
            location = str(loc_data.get("name", ""))

        apply_url = str(
            data.get(
                "absolute_url",
                data.get(
                    "applyUrl",
                    data.get(
                        "applicationUrl",
                        data.get("apply_url", str(raw_job.source_url)),
                    ),
                ),
            )
        )

        posted_date = self._extract_posted_date(data)
        # Include apply_url in hash for API jobs (jd_text may be empty)
        hash_input = jd_text if jd_text else apply_url
        content_hash = self._compute_hash(raw_job.company_name, title, hash_input)

        return NormalizedJob(
            raw_job_id=raw_job.id,
            company_id=raw_job.company_id,
            company_name=raw_job.company_name,
            title=title,
            jd_text=jd_text,
            apply_url=apply_url,
            location=location or None,
            posted_date=posted_date,
            content_hash=content_hash,
        )

    async def _process_from_html(self, raw_job: RawJob) -> NormalizedJob | None:
        """Use LLM to extract structured fields from HTML."""
        content = raw_job.raw_html or ""
        if len(content.strip()) < 100:
            logger.warning(
                "skipping_empty_content",
                company=raw_job.company_name,
                content_length=len(content.strip()),
                source_url=str(raw_job.source_url),
            )
            return None

        extracted = await self._call_llm(
            messages=[
                {
                    "role": "user",
                    "content": JOB_PROCESSOR_USER.format(
                        company_name=raw_job.company_name,
                        source_url=str(raw_job.source_url),
                        raw_content=content[:8000],
                    ),
                },
            ],
            model=self.settings.haiku_model,
            response_model=ExtractedJob,
        )

        if not extracted.is_valid_posting:
            logger.warning(
                "skipping_non_job_content",
                company=raw_job.company_name,
                title=extracted.title,
                source_url=str(raw_job.source_url),
            )
            return None

        content_hash = self._compute_hash(raw_job.company_name, extracted.title, extracted.jd_text)
        posted_date = self._parse_date_string(extracted.posted_date)

        return NormalizedJob(
            raw_job_id=raw_job.id,
            company_id=raw_job.company_id,
            company_name=raw_job.company_name,
            title=extracted.title,
            jd_text=extracted.jd_text,
            apply_url=extracted.apply_url or str(raw_job.source_url),
            location=extracted.location,
            remote_type=_normalize_remote_type(extracted.remote_type),
            posted_date=posted_date,
            salary_min=extracted.salary_min,
            salary_max=extracted.salary_max,
            currency=extracted.currency,
            required_skills=extracted.required_skills,
            preferred_skills=extracted.preferred_skills,
            required_experience_years=extracted.required_experience_years,
            seniority_level=extracted.seniority_level,
            department=extracted.department,
            content_hash=content_hash,
        )

    def _extract_posted_date(self, data: dict[str, object]) -> date | None:
        """Extract posted date from ATS JSON fields."""
        # Try known date fields in priority order
        for field_name in (
            "updated_at",
            "publishedAt",
            "published_at",
            "created_at",
            "date_posted",
            "createdAt",
        ):
            value = data.get(field_name)
            if value is None:
                continue
            # Unix ms timestamp (Lever uses createdAt as int)
            if isinstance(value, (int, float)) and value > 1_000_000_000:
                ts = value / 1000 if value > 1_000_000_000_000 else value
                return datetime.fromtimestamp(ts, tz=UTC).date()
            if isinstance(value, str):
                parsed = self._parse_date_string(value)
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _parse_date_string(value: str | None) -> date | None:
        """Parse a date string in common formats to date."""
        if not value:
            return None
        # Extract YYYY-MM-DD from the start of any ISO 8601 string
        date_part = value.split("T")[0].split("+")[0].strip()
        parts = date_part.split("-")
        if len(parts) == 3:
            try:
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
            except (ValueError, IndexError):
                pass
        return None

    def _compute_hash(self, company_name: str, title: str, jd_text: str) -> str:
        """Compute deduplication hash."""
        raw = f"{company_name}|{title}|{jd_text[:500]}"
        return hashlib.sha256(raw.encode()).hexdigest()
