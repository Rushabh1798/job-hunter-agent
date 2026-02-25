"""Jobs scraper agent — fetches raw jobs from career pages and ATS APIs."""

from __future__ import annotations

import asyncio
import time

import structlog

from job_hunter_agents.agents.base import BaseAgent
from job_hunter_agents.tools.ats_clients.ashby import AshbyClient
from job_hunter_agents.tools.ats_clients.greenhouse import GreenhouseClient
from job_hunter_agents.tools.ats_clients.lever import LeverClient
from job_hunter_agents.tools.ats_clients.workday import WorkdayClient
from job_hunter_agents.tools.browser import WebScraper
from job_hunter_core.models.company import ATSType, Company
from job_hunter_core.models.job import RawJob
from job_hunter_core.state import PipelineState

logger = structlog.get_logger()


class JobsScraperAgent(BaseAgent):
    """Scrape raw job listings from company career pages."""

    agent_name = "jobs_scraper"

    async def run(self, state: PipelineState) -> PipelineState:
        """Scrape jobs from all companies concurrently."""
        self._log_start({"companies_count": len(state.companies)})
        start = time.monotonic()

        semaphore = asyncio.Semaphore(self.settings.max_concurrent_scrapers)
        tasks = [self._scrape_company(company, semaphore, state) for company in state.companies]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                state.raw_jobs.extend(result)
            elif isinstance(result, Exception):
                self._record_error(state, result)

        self._log_end(
            time.monotonic() - start,
            {
                "raw_jobs_count": len(state.raw_jobs),
            },
        )
        return state

    async def _scrape_company(
        self,
        company: Company,
        semaphore: asyncio.Semaphore,
        state: PipelineState,
    ) -> list[RawJob]:
        """Scrape a single company with rate limiting."""
        async with semaphore:
            try:
                return await self._do_scrape(company)
            except Exception as e:
                self._record_error(state, e, company_name=company.name)
                return []

    async def _do_scrape(self, company: Company) -> list[RawJob]:
        """Execute scraping strategy for a company."""
        career_page = company.career_page
        strategy = career_page.scrape_strategy
        career_url = str(career_page.url)

        if strategy == "api":
            return await self._scrape_via_api(company)
        return await self._scrape_via_crawler(company, career_url)

    async def _scrape_via_api(self, company: Company) -> list[RawJob]:
        """Scrape via ATS API client."""
        ats_type = company.career_page.ats_type
        clients = {
            ATSType.GREENHOUSE: GreenhouseClient(),
            ATSType.LEVER: LeverClient(),
            ATSType.ASHBY: AshbyClient(),
            ATSType.WORKDAY: WorkdayClient(),
        }

        client = clients.get(ats_type)
        if not client:
            return await self._scrape_via_crawler(company, str(company.career_page.url))

        raw_dicts = await client.fetch_jobs(company)
        return [
            RawJob(
                company_id=company.id,
                company_name=company.name,
                raw_json=job_dict,
                source_url=company.career_page.url,
                scrape_strategy="api",
                source_confidence=0.95,
            )
            for job_dict in raw_dicts
        ]

    async def _scrape_via_crawler(self, company: Company, career_url: str) -> list[RawJob]:
        """Scrape via web crawler."""
        scraper = WebScraper()
        content = await scraper.fetch_page(career_url)

        return [
            RawJob(
                company_id=company.id,
                company_name=company.name,
                raw_html=content,
                source_url=company.career_page.url,
                scrape_strategy="crawl4ai",
                source_confidence=0.7,
            )
        ]
