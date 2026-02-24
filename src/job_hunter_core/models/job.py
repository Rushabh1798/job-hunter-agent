"""Job listing models — raw, normalized, scored."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, model_validator


class RawJob(BaseModel):
    """Raw job data as scraped from a career page or ATS API."""

    id: UUID = Field(default_factory=uuid4, description="Unique raw job identifier")
    company_id: UUID = Field(description="Reference to parent company")
    company_name: str = Field(description="Company name (denormalized for convenience)")
    raw_html: str | None = Field(default=None, description="Raw HTML content")
    raw_json: dict[str, object] | None = Field(default=None, description="Raw JSON from ATS API")
    source_url: HttpUrl = Field(description="URL where this job was found")
    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this job was scraped"
    )
    scrape_strategy: str = Field(description="Strategy used to scrape this job")
    source_confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in data quality"
    )


class NormalizedJob(BaseModel):
    """Structured job listing after LLM processing."""

    id: UUID = Field(default_factory=uuid4, description="Unique normalized job identifier")
    raw_job_id: UUID = Field(description="Reference to source raw job")
    company_id: UUID = Field(description="Reference to parent company")
    company_name: str = Field(description="Company name")
    title: str = Field(description="Job title")
    jd_text: str = Field(description="Full job description text")
    apply_url: HttpUrl = Field(description="Direct application URL")
    location: str | None = Field(default=None, description="Job location")
    remote_type: Literal["onsite", "hybrid", "remote", "unknown"] = Field(
        default="unknown", description="Remote work type"
    )
    posted_date: date | None = Field(default=None, description="Date job was posted")
    salary_min: int | None = Field(default=None, description="Minimum salary")
    salary_max: int | None = Field(default=None, description="Maximum salary")
    currency: str | None = Field(default=None, description="Salary currency")
    required_skills: list[str] = Field(
        default_factory=list, description="Required skills from JD"
    )
    preferred_skills: list[str] = Field(
        default_factory=list, description="Preferred/nice-to-have skills"
    )
    required_experience_years: float | None = Field(
        default=None, description="Required years of experience"
    )
    seniority_level: str | None = Field(default=None, description="Inferred seniority level")
    department: str | None = Field(default=None, description="Department or team")
    content_hash: str = Field(
        description="SHA-256 hash of company_name + title + jd_text[:500] for deduplication"
    )
    processed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this job was processed"
    )
    embedding: list[float] | None = Field(
        default=None, description="Embedding vector for semantic search"
    )

    @model_validator(mode="after")
    def validate_salary_range(self) -> NormalizedJob:
        """Ensure salary_min <= salary_max when both are set."""
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            msg = f"salary_min ({self.salary_min}) > salary_max ({self.salary_max})"
            raise ValueError(msg)
        return self


class FitReport(BaseModel):
    """Detailed fit analysis between a candidate and a job."""

    score: int = Field(ge=0, le=100, description="Overall fit score 0-100")
    skill_overlap: list[str] = Field(description="Skills the candidate has that match the JD")
    skill_gaps: list[str] = Field(description="Skills required by JD that candidate lacks")
    seniority_match: bool = Field(description="Whether seniority level matches")
    location_match: bool = Field(description="Whether location preferences match")
    org_type_match: bool = Field(description="Whether org type preferences match")
    summary: str = Field(description="Human-readable fit summary")
    recommendation: Literal["strong_match", "good_match", "stretch", "mismatch"] = Field(
        description="Overall recommendation category"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in this assessment"
    )


class ScoredJob(BaseModel):
    """A normalized job with its fit report and ranking."""

    job: NormalizedJob = Field(description="The normalized job listing")
    fit_report: FitReport = Field(description="Detailed fit analysis")
    rank: int | None = Field(default=None, description="Rank position in results")
    scored_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this job was scored"
    )
