"""Lever ATS client."""

from __future__ import annotations

import re

import httpx
import structlog

from job_hunter_agents.tools.ats_clients.base import BaseATSClient
from job_hunter_core.models.company import Company

logger = structlog.get_logger()

LEVER_PATTERN = re.compile(r"jobs\.lever\.co/(\w[\w-]*)", re.IGNORECASE)
LEVER_API_URL = "https://api.lever.co/v0/postings/{slug}"


class LeverClient(BaseATSClient):
    """Client for Lever ATS public API."""

    async def detect(self, career_url: str) -> bool:
        """Detect if URL points to a Lever board."""
        return bool(LEVER_PATTERN.search(career_url))

    def _extract_slug(self, career_url: str) -> str | None:
        """Extract the company slug from a Lever URL."""
        match = LEVER_PATTERN.search(career_url)
        return match.group(1) if match else None

    async def fetch_jobs(self, company: Company) -> list[dict]:  # type: ignore[type-arg]
        """Fetch jobs from Lever API."""
        url = str(company.career_page.url)
        slug = self._extract_slug(url)
        if not slug:
            logger.warning("lever_no_slug", url=url)
            return []

        api_url = LEVER_API_URL.format(slug=slug)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            jobs = response.json()
            logger.info(
                "lever_jobs_fetched",
                company=company.name,
                count=len(jobs),
            )
            return jobs  # type: ignore[no-any-return]
