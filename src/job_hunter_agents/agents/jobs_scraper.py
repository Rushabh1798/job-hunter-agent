"""Jobs scraper agent — fetches raw jobs from career pages and ATS APIs."""

from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urljoin

import structlog

from job_hunter_agents.agents.base import BaseAgent
from job_hunter_agents.tools.ats_clients.ashby import AshbyClient
from job_hunter_agents.tools.ats_clients.greenhouse import GreenhouseClient
from job_hunter_agents.tools.ats_clients.lever import LeverClient
from job_hunter_agents.tools.ats_clients.workday import WorkdayClient
from job_hunter_agents.tools.factories import create_page_scraper
from job_hunter_core.interfaces.scraper import PageScraper
from job_hunter_core.models.company import ATSType, Company
from job_hunter_core.models.job import RawJob
from job_hunter_core.state import PipelineState

logger = structlog.get_logger()

# Patterns matching individual job posting URLs
_JOB_LINK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"/jobs?/\d+", re.IGNORECASE),
    re.compile(r"/positions?/\d+", re.IGNORECASE),
    re.compile(r"/opening/", re.IGNORECASE),
    re.compile(r"greenhouse\.io/.+/jobs/", re.IGNORECASE),
    re.compile(r"lever\.co/.+/", re.IGNORECASE),
    re.compile(r"boards\.greenhouse\.io/", re.IGNORECASE),
    re.compile(r"jobs\.lever\.co/", re.IGNORECASE),
    re.compile(r"jobs\.ashbyhq\.com/", re.IGNORECASE),
    re.compile(r"workday\.com/.*/job/", re.IGNORECASE),
    re.compile(r"/careers/.*/apply", re.IGNORECASE),
    re.compile(r"/careers/.*\d{4,}", re.IGNORECASE),
]

# Links to skip (non-job pages)
_SKIP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"/(about|blog|contact|privacy|terms|login|signup|faq|press)", re.IGNORECASE),
    re.compile(r"\.(css|js|png|jpg|svg|gif|ico|pdf)$", re.IGNORECASE),
    re.compile(r"^(mailto:|tel:|javascript:)", re.IGNORECASE),
]

_MAX_JOB_LINKS_PER_COMPANY = 20
_LINK_FETCH_CONCURRENCY = 3


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
        """Scrape career page, extract job links, fetch each individual posting."""
        scraper = create_page_scraper()
        landing_html = await scraper.fetch_page(career_url)

        job_links = self._extract_job_links(landing_html, career_url)

        if not job_links:
            logger.info(
                "no_job_links_found_using_landing",
                company=company.name,
                url=career_url,
            )
            return [
                RawJob(
                    company_id=company.id,
                    company_name=company.name,
                    raw_html=landing_html,
                    source_url=company.career_page.url,
                    scrape_strategy="crawl4ai",
                    source_confidence=0.7,
                )
            ]

        logger.info(
            "job_links_extracted",
            company=company.name,
            link_count=len(job_links),
        )
        return await self._fetch_job_pages(company, scraper, job_links)

    async def _fetch_job_pages(
        self,
        company: Company,
        scraper: PageScraper,
        job_links: list[str],
    ) -> list[RawJob]:
        """Fetch individual job pages concurrently with bounded concurrency."""
        sem = asyncio.Semaphore(_LINK_FETCH_CONCURRENCY)
        raw_jobs: list[RawJob] = []

        async def _fetch_one(url: str) -> RawJob | None:
            async with sem:
                try:
                    content = await scraper.fetch_page(url)
                    return RawJob(
                        company_id=company.id,
                        company_name=company.name,
                        raw_html=content,
                        source_url=url,  # type: ignore[arg-type]
                        scrape_strategy="crawl4ai",
                        source_confidence=0.85,
                    )
                except Exception:
                    logger.warning(
                        "job_page_fetch_failed",
                        company=company.name,
                        url=url,
                    )
                    return None

        results = await asyncio.gather(*[_fetch_one(u) for u in job_links])
        for r in results:
            if r is not None:
                raw_jobs.append(r)

        return raw_jobs

    @staticmethod
    def _extract_job_links(html: str, base_url: str) -> list[str]:
        """Extract individual job posting URLs from career page HTML.

        Parses anchor tags, matches known job-URL patterns, filters
        non-job links, deduplicates, and limits to _MAX_JOB_LINKS_PER_COMPANY.
        """
        href_re = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)
        raw_hrefs = href_re.findall(html)

        seen: set[str] = set()
        job_links: list[str] = []

        for href in raw_hrefs:
            # Skip non-job pages
            if any(p.search(href) for p in _SKIP_PATTERNS):
                continue

            # Resolve relative URLs
            full_url = urljoin(base_url, href)
            normalized = full_url.split("#")[0].split("?")[0].rstrip("/")

            if normalized in seen or normalized == base_url.rstrip("/"):
                continue

            # Check if URL matches any job-link pattern
            if not any(p.search(full_url) for p in _JOB_LINK_PATTERNS):
                continue

            seen.add(normalized)
            job_links.append(full_url)

            if len(job_links) >= _MAX_JOB_LINKS_PER_COMPANY:
                break

        return job_links
