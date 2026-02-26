"""Company finder agent — discovers target companies using LLM + web search."""

from __future__ import annotations

import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

from job_hunter_agents.agents.base import BaseAgent
from job_hunter_agents.prompts.company_finder import (
    COMPANY_FINDER_USER,
)
from job_hunter_agents.tools.ats_clients.ashby import AshbyClient
from job_hunter_agents.tools.ats_clients.greenhouse import GreenhouseClient
from job_hunter_agents.tools.ats_clients.lever import LeverClient
from job_hunter_agents.tools.ats_clients.workday import WorkdayClient
from job_hunter_agents.tools.factories import create_search_provider
from job_hunter_core.exceptions import FatalAgentError
from job_hunter_core.models.company import ATSType, CareerPage, Company, CompanyTier
from job_hunter_core.state import PipelineState

logger = structlog.get_logger()


class CompanyCandidate(BaseModel):
    """LLM-generated company candidate."""

    name: str = Field(description="Company name")
    domain: str = Field(description="Company website domain")
    industry: str | None = Field(default=None, description="Industry")
    size: str | None = Field(default=None, description="Company size")
    tier: str = Field(
        default="unknown",
        description="Company tier: tier_1, tier_2, tier_3, startup",
    )
    description: str | None = Field(default=None, description="Brief description")


class CompanyCandidateList(BaseModel):
    """List of company candidates from LLM."""

    companies: list[CompanyCandidate] = Field(description="Target companies")


class CompanyFinderAgent(BaseAgent):
    """Discover target companies matching candidate profile and preferences."""

    agent_name = "company_finder"

    async def run(self, state: PipelineState) -> PipelineState:
        """Find companies, validate career pages, detect ATS types."""
        self._log_start()
        start = time.monotonic()

        if state.profile is None or state.preferences is None:
            msg = "Profile and preferences must be parsed before finding companies"
            raise FatalAgentError(msg)

        # Step 1: Generate candidates
        candidates = await self._generate_candidates(state)

        # Step 2: Validate career pages and detect ATS
        companies: list[Company] = []
        for candidate in candidates:
            try:
                company = await self._validate_and_build(candidate)
                if company:
                    companies.append(company)
            except Exception as e:
                self._record_error(state, e, company_name=candidate.name)

        if not companies:
            msg = "No companies found with valid career pages"
            raise FatalAgentError(msg)

        # Apply company limit if set
        if state.config.company_limit:
            companies = companies[: state.config.company_limit]

        state.companies = companies
        self._log_end(
            time.monotonic() - start,
            {
                "companies_found": len(companies),
            },
        )
        return state

    async def _generate_candidates(self, state: PipelineState) -> list[CompanyCandidate]:
        """Generate company candidates via LLM or preferences."""
        profile = state.profile
        prefs = state.preferences
        assert profile is not None
        assert prefs is not None

        # If user specified preferred companies, use those
        if prefs.preferred_companies:
            return [
                CompanyCandidate(name=name, domain=f"{name.lower().replace(' ', '')}.com")
                for name in prefs.preferred_companies
            ]

        # Use profile as fallback when prefs fields are empty
        locations = ", ".join(prefs.preferred_locations) or profile.location or "Any"
        target_titles = ", ".join(prefs.target_titles) or profile.current_title or "Any"
        industries = ", ".join(prefs.preferred_industries) or ", ".join(profile.industries) or "Any"
        seniority = ", ".join(prefs.target_seniority) or profile.seniority_level or "Any"

        # Merge user exclusions with already-attempted companies
        all_excluded = set(prefs.excluded_companies) | state.attempted_company_names
        excluded_str = ", ".join(sorted(all_excluded)) or "None"

        result = await self._call_llm(
            messages=[
                {
                    "role": "user",
                    "content": COMPANY_FINDER_USER.format(
                        name=profile.name,
                        current_title=profile.current_title or "Not specified",
                        years_of_experience=profile.years_of_experience,
                        skills=", ".join(s.name for s in profile.skills),
                        industries=", ".join(profile.industries) or "Not specified",
                        tech_stack=", ".join(profile.tech_stack) or "Not specified",
                        target_titles=target_titles,
                        target_seniority=seniority,
                        preferred_locations=locations,
                        remote_preference=prefs.remote_preference,
                        preferred_industries=industries,
                        org_types=", ".join(prefs.org_types),
                        company_sizes=", ".join(prefs.company_sizes) or "Any",
                        excluded_companies=excluded_str,
                        preferred_companies=", ".join(prefs.preferred_companies) or "None",
                        salary_currency=prefs.currency,
                    ),
                },
            ],
            model=self.settings.sonnet_model,
            response_model=CompanyCandidateList,
            state=state,
        )
        return result.companies

    async def _validate_and_build(self, candidate: CompanyCandidate) -> Company | None:
        """Validate career page exists and build Company model."""
        career_url = await self._find_career_url(candidate)
        if not career_url:
            logger.warning("career_page_not_found", company=candidate.name)
            return None

        ats_type, strategy = await self._detect_ats(career_url)
        tier = self._map_tier(candidate.tier)

        return Company(
            name=candidate.name,
            domain=candidate.domain,
            career_page=CareerPage(
                url=career_url,
                ats_type=ats_type,
                scrape_strategy=strategy,
            ),
            industry=candidate.industry,
            size=candidate.size,
            tier=tier,
            description=candidate.description,
        )

    @staticmethod
    def _map_tier(tier_str: str) -> CompanyTier:
        """Map raw tier string from LLM to CompanyTier enum."""
        try:
            return CompanyTier(tier_str.lower().strip())
        except ValueError:
            return CompanyTier.UNKNOWN

    async def _find_career_url(self, candidate: CompanyCandidate) -> str | None:
        """Find the career page URL for a company."""
        search_tool = create_search_provider(self.settings)
        return await search_tool.find_career_page(candidate.name)

    async def _detect_ats(self, career_url: str) -> tuple[ATSType, str]:
        """Detect ATS type from career URL patterns."""
        clients: list[tuple[Any, ATSType]] = [
            (GreenhouseClient(), ATSType.GREENHOUSE),
            (LeverClient(), ATSType.LEVER),
            (AshbyClient(), ATSType.ASHBY),
            (WorkdayClient(), ATSType.WORKDAY),
        ]

        for client, ats_type in clients:
            if await client.detect(career_url):
                return ats_type, "api"

        return ATSType.UNKNOWN, "crawl4ai"
