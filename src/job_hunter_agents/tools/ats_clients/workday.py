"""Workday ATS client (crawl4ai-based, no public API)."""

from __future__ import annotations

import re

import structlog

from job_hunter_agents.tools.ats_clients.base import BaseATSClient
from job_hunter_agents.tools.browser import WebScraper
from job_hunter_core.models.company import Company

logger = structlog.get_logger()

WORKDAY_PATTERN = re.compile(r"myworkdayjobs\.com|workday\.com/en-US", re.IGNORECASE)


class WorkdayClient(BaseATSClient):
    """Client for Workday ATS (crawl4ai-based, no public API)."""

    def __init__(self) -> None:
        """Initialize with a web scraper."""
        self._scraper = WebScraper()

    async def detect(self, career_url: str) -> bool:
        """Detect if URL points to a Workday-based career page."""
        return bool(WORKDAY_PATTERN.search(career_url))

    async def fetch_jobs(self, company: Company) -> list[dict]:  # type: ignore[type-arg]
        """Fetch jobs by scraping Workday career page."""
        url = str(company.career_page.url)
        try:
            content = await self._scraper.fetch_page(url)
            logger.info(
                "workday_page_fetched",
                company=company.name,
                content_length=len(content),
            )
            return [{"raw_content": content, "source_url": url}]
        except Exception as e:
            logger.error("workday_scrape_failed", company=company.name, error=str(e))
            return []
