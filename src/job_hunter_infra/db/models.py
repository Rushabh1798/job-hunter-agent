"""SQLAlchemy ORM table models."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class ProfileModel(Base):
    """Candidate profile table."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    years_of_experience: Mapped[float] = mapped_column(Float, nullable=False)
    seniority_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    skills_json: Mapped[dict] = mapped_column(JSON, nullable=False)  # type: ignore[type-arg]
    education_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    past_titles_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    industries_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    tech_stack_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class CompanyModel(Base):
    """Company table."""

    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ats_type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    career_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    api_endpoint: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    org_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    scrape_strategy: Mapped[str] = mapped_column(String(50), default="crawl4ai")
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class RawJobModel(Base):
    """Raw scraped job data table."""

    __tablename__ = "jobs_raw"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id"), nullable=False
    )
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    raw_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    scrape_strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    source_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class NormalizedJobModel(Base):
    """Normalized job listing table with optional embedding."""

    __tablename__ = "jobs_normalized"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    raw_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("jobs_raw.id"), nullable=True
    )
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id"), nullable=False
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    jd_text: Mapped[str] = mapped_column(Text, nullable=False)
    apply_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remote_type: Mapped[str] = mapped_column(String(50), default="unknown")
    posted_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    required_skills_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    preferred_skills_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    required_experience_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    seniority_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ScoredJobModel(Base):
    """Scored job results table."""

    __tablename__ = "jobs_scored"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    normalized_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs_normalized.id"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    skill_overlap_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    skill_gaps_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    seniority_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    location_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    org_type_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fit_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class RunHistoryModel(Base):
    """Run history table."""

    __tablename__ = "run_history"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    run_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    companies_attempted: Mapped[int] = mapped_column(Integer, default=0)
    companies_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    jobs_scraped: Mapped[int] = mapped_column(Integer, default=0)
    jobs_scored: Mapped[int] = mapped_column(Integer, default=0)
    jobs_in_output: Mapped[int] = mapped_column(Integer, default=0)
    output_files_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    errors_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[type-arg]
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
