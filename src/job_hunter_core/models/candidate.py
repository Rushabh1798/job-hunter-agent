"""Candidate profile and search preferences models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, HttpUrl, model_validator


class Skill(BaseModel):
    """A single skill with optional proficiency level."""

    name: str = Field(description="Skill name")
    level: Literal["beginner", "intermediate", "advanced", "expert"] | None = Field(
        default=None, description="Proficiency level"
    )
    years: float | None = Field(default=None, description="Years of experience with this skill")


class Education(BaseModel):
    """Educational background entry."""

    degree: str | None = Field(default=None, description="Degree type (BS, MS, PhD, etc.)")
    field: str | None = Field(default=None, description="Field of study")
    institution: str | None = Field(default=None, description="University/college name")
    graduation_year: int | None = Field(default=None, description="Year of graduation")

    @model_validator(mode="after")
    def validate_graduation_year(self) -> Education:
        """Ensure graduation year is within reasonable range."""
        if self.graduation_year is not None and not (1950 <= self.graduation_year <= 2030):
            msg = f"graduation_year {self.graduation_year} outside valid range 1950-2030"
            raise ValueError(msg)
        return self


class CandidateProfile(BaseModel):
    """Structured representation of a candidate's resume."""

    name: str = Field(description="Full name")
    email: EmailStr = Field(description="Contact email address")
    phone: str | None = Field(default=None, description="Phone number")
    location: str | None = Field(default=None, description="Current location")
    linkedin_url: HttpUrl | None = Field(default=None, description="LinkedIn profile URL")
    github_url: HttpUrl | None = Field(default=None, description="GitHub profile URL")
    current_title: str | None = Field(default=None, description="Current job title")
    years_of_experience: float = Field(ge=0, description="Total years of professional experience")
    skills: list[Skill] = Field(description="List of skills")
    past_titles: list[str] = Field(default_factory=list, description="Previous job titles")
    industries: list[str] = Field(default_factory=list, description="Industries worked in")
    education: list[Education] = Field(default_factory=list, description="Education entries")
    seniority_level: Literal[
        "intern", "junior", "mid", "senior", "staff",
        "principal", "director", "vp", "c-level",
    ] | None = Field(default=None, description="Inferred seniority level")
    tech_stack: list[str] = Field(default_factory=list, description="Technologies used")
    raw_text: str = Field(description="Raw extracted text from resume")
    parsed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When the resume was parsed"
    )
    content_hash: str = Field(description="SHA-256 hash of raw_text for cache invalidation")


class SearchPreferences(BaseModel):
    """Structured job search preferences parsed from freeform text."""

    preferred_locations: list[str] = Field(
        default_factory=list, description="Preferred work locations"
    )
    remote_preference: Literal["onsite", "hybrid", "remote", "any"] = Field(
        default="any", description="Remote work preference"
    )
    target_titles: list[str] = Field(
        default_factory=list, description="Desired job titles"
    )
    target_seniority: list[str] = Field(
        default_factory=list, description="Target seniority levels"
    )
    excluded_titles: list[str] = Field(
        default_factory=list, description="Job titles to exclude"
    )
    org_types: list[str] = Field(
        default_factory=lambda: ["any"], description="Preferred organization types"
    )
    company_sizes: list[
        Literal["1-10", "11-50", "51-200", "201-500", "501-1000", "1001+"]
    ] = Field(default_factory=list, description="Preferred company sizes")
    preferred_industries: list[str] = Field(
        default_factory=list, description="Preferred industries"
    )
    excluded_companies: list[str] = Field(
        default_factory=list, description="Companies to exclude"
    )
    preferred_companies: list[str] = Field(
        default_factory=list, description="Specific companies to target"
    )
    min_salary: int | None = Field(default=None, description="Minimum desired salary")
    max_salary: int | None = Field(default=None, description="Maximum desired salary")
    currency: str = Field(default="USD", description="Salary currency")
    raw_text: str = Field(description="Original freeform preferences text")

    @model_validator(mode="after")
    def validate_salary_range(self) -> SearchPreferences:
        """Ensure min_salary <= max_salary when both are set."""
        if (
            self.min_salary is not None
            and self.max_salary is not None
            and self.min_salary > self.max_salary
        ):
            msg = f"min_salary ({self.min_salary}) cannot exceed max_salary ({self.max_salary})"
            raise ValueError(msg)
        return self
