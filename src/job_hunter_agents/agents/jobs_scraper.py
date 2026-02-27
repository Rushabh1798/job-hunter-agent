"""Jobs scraper agent — fetches raw jobs from career pages and ATS APIs."""

from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urljoin, urlparse

import httpx
import structlog

from job_hunter_agents.agents.base import BaseAgent
from job_hunter_agents.tools.ats_clients.ashby import (
    ASHBY_API_URL,
    ASHBY_PATTERN,
    AshbyClient,
)
from job_hunter_agents.tools.ats_clients.greenhouse import (
    GREENHOUSE_API_URL,
    GREENHOUSE_BOARD_PATTERN,
    GreenhouseClient,
)
from job_hunter_agents.tools.ats_clients.lever import (
    LEVER_API_URL,
    LEVER_PATTERN,
    LeverClient,
)
from job_hunter_agents.tools.ats_clients.workday import WorkdayClient
from job_hunter_agents.tools.factories import create_page_scraper, create_search_provider
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

# ATS board detection: maps pattern → (ats_name, api_url_template)
_ATS_BOARD_DETECTORS: list[tuple[re.Pattern[str], str, str]] = [
    (GREENHOUSE_BOARD_PATTERN, "greenhouse", GREENHOUSE_API_URL),
    (LEVER_PATTERN, "lever", LEVER_API_URL),
    (ASHBY_PATTERN, "ashby", ASHBY_API_URL),
]


def _detect_ats_board(url: str) -> tuple[str, str, str] | None:
    """Detect ATS board type and slug from a URL.

    Returns (ats_name, slug, api_url) or None.
    """
    for pattern, ats_name, api_template in _ATS_BOARD_DETECTORS:
        match = pattern.search(url)
        if match:
            slug = match.group(1)
            return (ats_name, slug, api_template.format(slug=slug))
    return None


def _company_name_matches_slug(company_name: str, slug: str) -> bool:
    """Check if a company name plausibly matches an ATS URL slug.

    Uses exact word matching to avoid false positives like "meta" matching
    "metabase" (Metabase is a different company than Meta).
    """
    name_lower = company_name.lower().replace(" ", "").replace("-", "")
    slug_lower = slug.lower().replace("-", "")
    first_word = company_name.lower().split()[0] if company_name.split() else ""
    # Exact match: "Stripe" → "stripe", "TigerAnalytics" → "tigeranalytics"
    if slug_lower == name_lower:
        return True
    # Slug equals the first word: "NVIDIA India" → slug "nvidia"
    if first_word and slug_lower == first_word:
        return True
    return False


class JobsScraperAgent(BaseAgent):
    """Scrape raw job listings from company career pages."""

    agent_name = "jobs_scraper"

    async def run(self, state: PipelineState) -> PipelineState:
        """Scrape jobs from all companies concurrently.

        Jobs are accumulated into state.raw_jobs incrementally so that
        partial results are preserved if the agent times out.
        """
        self._log_start({"companies_count": len(state.companies)})
        start = time.monotonic()

        semaphore = asyncio.Semaphore(self.settings.max_concurrent_scrapers)

        async def _scrape_and_accumulate(company: Company) -> None:
            """Scrape a company and add jobs to state immediately."""
            async with semaphore:
                try:
                    jobs = await self._do_scrape(company, state)
                    state.raw_jobs.extend(jobs)
                except Exception as e:
                    self._record_error(state, e, company_name=company.name)

        tasks = [_scrape_and_accumulate(c) for c in state.companies]
        await asyncio.gather(*tasks, return_exceptions=True)

        self._log_end(
            time.monotonic() - start,
            {"raw_jobs_count": len(state.raw_jobs)},
        )
        return state

    async def _do_scrape(self, company: Company, state: PipelineState) -> list[RawJob]:
        """Execute scraping strategy for a company."""
        career_page = company.career_page
        strategy = career_page.scrape_strategy
        career_url = str(career_page.url)

        if strategy == "api":
            return await self._scrape_via_api(company, state)
        return await self._scrape_via_crawler(company, career_url, state)

    async def _scrape_via_api(self, company: Company, state: PipelineState) -> list[RawJob]:
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
            return await self._scrape_via_crawler(company, str(company.career_page.url), state)

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

    async def _scrape_via_crawler(
        self,
        company: Company,
        career_url: str,
        state: PipelineState,
    ) -> list[RawJob]:
        """Scrape career page, extract job links, fetch each individual posting.

        Strategy order (fastest/most reliable first):
        1. Probe ATS boards by company name slug (deterministic HTTP, ~1s)
        2. Crawl landing page and extract links from HTML
        3. Search for job links via DuckDuckGo
        4. Fall back to landing page HTML as a single raw job
        """
        # Step 1: Probe ATS boards FIRST — fast, reliable, returns structured JSON
        ats_jobs = await self._probe_ats_boards(company)
        if ats_jobs:
            return ats_jobs

        # Step 2: Crawl landing page and extract links
        scraper = create_page_scraper()
        landing_html = await scraper.fetch_page(career_url)
        job_links = self._extract_job_links(landing_html, career_url)

        if not job_links:
            job_links = await self._search_job_links(company, career_url, state)

        if not job_links:
            logger.info("no_job_links_found_using_landing", company=company.name, url=career_url)
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

        logger.info("job_links_extracted", company=company.name, link_count=len(job_links))

        # Try ATS APIs first for links on ATS platforms (structured JSON > crawled HTML)
        api_jobs, remaining_links = await self._try_ats_boards(company, job_links)
        if api_jobs:
            logger.info("ats_api_jobs_fetched", company=company.name, count=len(api_jobs))

        crawled_jobs = await self._fetch_job_pages(company, scraper, remaining_links)
        return api_jobs + crawled_jobs

    async def _search_job_links(
        self,
        company: Company,
        career_url: str,
        state: PipelineState,
    ) -> list[str]:
        """Search for individual job postings at this company."""
        prefs = state.preferences
        profile = state.profile

        titles: list[str] = []
        if prefs and prefs.target_titles:
            titles = prefs.target_titles[:2]
        elif profile and profile.current_title:
            titles = [profile.current_title]

        role_term = " OR ".join(f'"{t}"' for t in titles) if titles else "engineer"
        clean_name = company.name.strip()

        try:
            search_tool = create_search_provider(self.settings)
        except Exception:
            return []

        # Strategy 1: Search ATS platforms with real APIs (skip Workday — no public API)
        ats_query = (
            f'"{clean_name}" {role_term} '
            f"site:boards.greenhouse.io OR site:jobs.lever.co OR site:jobs.ashbyhq.com"
        )
        # Strategy 2: Direct job posting search on company domain
        direct_query = f'"{clean_name}" {role_term} job apply'

        all_links: list[str] = []
        seen: set[str] = set()
        ats_hosts = {"greenhouse.io", "lever.co", "ashbyhq.com"}
        base_domain = urlparse(career_url).netloc.removeprefix("www.")

        for query in (ats_query, direct_query):
            try:
                results = await search_tool.search(query, max_results=5)
            except Exception:
                continue

            for r in results:
                if not r.url or r.url in seen or r.url == career_url:
                    continue
                seen.add(r.url)
                host = urlparse(r.url).netloc.removeprefix("www.")

                is_company_domain = base_domain in host
                is_ats = any(h in host for h in ats_hosts)

                if is_ats:
                    # Validate ATS URL matches this company (not a different one)
                    board = _detect_ats_board(r.url)
                    if board and not _company_name_matches_slug(clean_name, board[1]):
                        logger.debug(
                            "skipping_ats_wrong_company",
                            company=clean_name,
                            slug=board[1],
                            url=r.url,
                        )
                        continue
                    all_links.append(r.url)
                elif is_company_domain:
                    all_links.append(r.url)

            if all_links:
                break

        if all_links:
            logger.info("search_found_job_links", company=company.name, link_count=len(all_links))
        return all_links[:_MAX_JOB_LINKS_PER_COMPANY]

    async def _try_ats_boards(
        self,
        company: Company,
        job_links: list[str],
    ) -> tuple[list[RawJob], list[str]]:
        """Route ATS board URLs through APIs. Returns (api_jobs, remaining_links)."""
        boards: dict[str, str] = {}  # slug → api_url (deduplicated)
        remaining: list[str] = []

        for url in job_links:
            board = _detect_ats_board(url)
            if board:
                _, slug, api_url = board
                boards[slug] = api_url
            elif "myworkdayjobs.com" in url.lower() or "workday.com" in url.lower():
                logger.debug("skipping_workday_url", company=company.name, url=url)
            else:
                remaining.append(url)

        if not boards:
            return ([], remaining)

        api_jobs: list[RawJob] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for slug, api_url in boards.items():
                try:
                    resp = await client.get(api_url)
                    resp.raise_for_status()
                    data = resp.json()
                    jobs = data.get("jobs", data) if isinstance(data, dict) else data
                    if not isinstance(jobs, list):
                        jobs = [data]
                    for job_dict in jobs[:_MAX_JOB_LINKS_PER_COMPANY]:
                        api_jobs.append(
                            RawJob(
                                company_id=company.id,
                                company_name=company.name,
                                raw_json=job_dict,
                                source_url=api_url,  # type: ignore[arg-type]
                                scrape_strategy="api",
                                source_confidence=0.95,
                            )
                        )
                    logger.info(
                        "ats_board_api_success",
                        company=company.name,
                        slug=slug,
                        jobs_count=len(jobs),
                    )
                except Exception:
                    logger.warning("ats_board_api_failed", company=company.name, slug=slug)

        return (api_jobs, remaining)

    async def _probe_ats_boards(self, company: Company) -> list[RawJob]:
        """Probe known ATS boards by company name slug (deterministic, no search)."""
        slug = company.name.lower().replace(" ", "").replace("-", "")
        # Also try first word as slug (e.g., "NVIDIA India" → "nvidia")
        first_word = company.name.lower().split()[0] if company.name.split() else slug

        api_templates = [
            ("greenhouse", GREENHOUSE_API_URL),
            ("lever", LEVER_API_URL),
            ("ashby", ASHBY_API_URL),
        ]

        async with httpx.AsyncClient(timeout=10.0) as client:
            for slug_candidate in dict.fromkeys([slug, first_word]):
                for ats_name, template in api_templates:
                    api_url = template.format(slug=slug_candidate)
                    try:
                        resp = await client.get(api_url)
                        if resp.status_code != 200:
                            continue
                        data = resp.json()
                        jobs = data.get("jobs", data) if isinstance(data, dict) else data
                        if not isinstance(jobs, list) or not jobs:
                            continue
                        logger.info(
                            "ats_board_probed_success",
                            company=company.name,
                            ats=ats_name,
                            slug=slug_candidate,
                            jobs_count=len(jobs),
                        )
                        return [
                            RawJob(
                                company_id=company.id,
                                company_name=company.name,
                                raw_json=job_dict,
                                source_url=api_url,  # type: ignore[arg-type]
                                scrape_strategy="api",
                                source_confidence=0.95,
                            )
                            for job_dict in jobs[:_MAX_JOB_LINKS_PER_COMPANY]
                        ]
                    except Exception:
                        continue
        return []

    async def _fetch_job_pages(
        self,
        company: Company,
        scraper: PageScraper,
        job_links: list[str],
    ) -> list[RawJob]:
        """Fetch individual job pages concurrently with bounded concurrency."""
        if not job_links:
            return []
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
                    logger.warning("job_page_fetch_failed", company=company.name, url=url)
                    return None

        results = await asyncio.gather(*[_fetch_one(u) for u in job_links])
        for r in results:
            if r is not None:
                raw_jobs.append(r)

        return raw_jobs

    @staticmethod
    def _extract_job_links(html: str, base_url: str) -> list[str]:
        """Extract individual job posting URLs from career page HTML."""
        href_re = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)
        raw_hrefs = href_re.findall(html)

        seen: set[str] = set()
        job_links: list[str] = []

        for href in raw_hrefs:
            if any(p.search(href) for p in _SKIP_PATTERNS):
                continue

            full_url = urljoin(base_url, href)
            normalized = full_url.split("#")[0].split("?")[0].rstrip("/")

            if normalized in seen or normalized == base_url.rstrip("/"):
                continue

            if not any(p.search(full_url) for p in _JOB_LINK_PATTERNS):
                continue

            seen.add(normalized)
            job_links.append(full_url)

            if len(job_links) >= _MAX_JOB_LINKS_PER_COMPANY:
                break

        return job_links
