"""Ashby ATS client."""

from __future__ import annotations

import re

import httpx
import structlog

from job_hunter_agents.tools.ats_clients.base import BaseATSClient
from job_hunter_core.models.company import Company

logger = structlog.get_logger()

ASHBY_PATTERN = re.compile(r"jobs\.ashbyhq\.com/(\w[\w-]*)", re.IGNORECASE)
ASHBY_API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


class AshbyClient(BaseATSClient):
    """Client for Ashby ATS public API."""

    async def detect(self, career_url: str) -> bool:
        """Detect if URL points to an Ashby job board."""
        return bool(ASHBY_PATTERN.search(career_url))

    def _extract_slug(self, career_url: str) -> str | None:
        """Extract the company slug from an Ashby URL."""
        match = ASHBY_PATTERN.search(career_url)
        return match.group(1) if match else None

    async def fetch_jobs(self, company: Company) -> list[dict]:  # type: ignore[type-arg]
        """Fetch jobs from Ashby API."""
        url = str(company.career_page.url)
        slug = self._extract_slug(url)
        if not slug:
            logger.warning("ashby_no_slug", url=url)
            return []

        api_url = ASHBY_API_URL.format(slug=slug)
        headers = {"User-Agent": "Mozilla/5.0 (compatible; JobHunter/1.0)"}
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            data = response.json()
            jobs = data.get("jobs", [])
            logger.info(
                "ashby_jobs_fetched",
                company=company.name,
                count=len(jobs),
            )
            return jobs  # type: ignore[no-any-return]
