"""Company and career page models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl


class CompanyTier(StrEnum):
    """Company tier classification."""

    TIER_1 = "tier_1"  # Big tech / FAANG-level, >10k employees
    TIER_2 = "tier_2"  # Established mid-to-large, 1k-10k employees
    TIER_3 = "tier_3"  # Growing companies, 200-1000 employees
    STARTUP = "startup"  # Early-to-growth stage, <200 employees
    UNKNOWN = "unknown"


class ATSType(StrEnum):
    """Applicant Tracking System types."""

    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    ASHBY = "ashby"
    ICIMS = "icims"
    TALEO = "taleo"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class CareerPage(BaseModel):
    """Career page metadata for a company."""

    url: HttpUrl = Field(description="Career page URL")
    ats_type: ATSType = Field(default=ATSType.UNKNOWN, description="Detected ATS type")
    api_endpoint: HttpUrl | None = Field(
        default=None, description="Direct ATS API endpoint if available"
    )
    last_scraped_at: datetime | None = Field(
        default=None, description="When this page was last scraped"
    )
    scrape_strategy: Literal["api", "crawl4ai", "playwright", "tavily"] = Field(
        default="crawl4ai", description="Scraping strategy to use"
    )


class Company(BaseModel):
    """A target company with career page information."""

    id: UUID = Field(default_factory=uuid4, description="Unique company identifier")
    name: str = Field(description="Company name")
    domain: str = Field(description="Company domain (e.g. 'stripe.com')")
    career_page: CareerPage = Field(description="Career page details")
    industry: str | None = Field(default=None, description="Industry sector")
    size: str | None = Field(default=None, description="Company size range")
    org_type: str | None = Field(
        default=None, description="Organization type (startup, enterprise, etc.)"
    )
    description: str | None = Field(default=None, description="Brief company description")
    tier: CompanyTier = Field(
        default=CompanyTier.UNKNOWN, description="Company tier classification"
    )
    source_confidence: float = Field(
        ge=0.0, le=1.0, default=1.0, description="Confidence in career page accuracy"
    )
