"""Greenhouse ATS client."""

from __future__ import annotations

import re

import httpx
import structlog

from job_hunter_agents.tools.ats_clients.base import BaseATSClient
from job_hunter_core.models.company import Company

logger = structlog.get_logger()

GREENHOUSE_BOARD_PATTERN = re.compile(
    r"boards\.greenhouse\.io/(\w+)", re.IGNORECASE
)
GREENHOUSE_API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


class GreenhouseClient(BaseATSClient):
    """Client for Greenhouse ATS public API."""

    async def detect(self, career_url: str) -> bool:
        """Detect if URL points to a Greenhouse board."""
        return bool(GREENHOUSE_BOARD_PATTERN.search(career_url))

    def _extract_slug(self, career_url: str) -> str | None:
        """Extract the board slug from a Greenhouse URL."""
        match = GREENHOUSE_BOARD_PATTERN.search(career_url)
        return match.group(1) if match else None

    async def fetch_jobs(self, company: Company) -> list[dict]:  # type: ignore[type-arg]
        """Fetch jobs from Greenhouse API."""
        url = str(company.career_page.url)
        slug = self._extract_slug(url)
        if not slug:
            logger.warning("greenhouse_no_slug", url=url)
            return []

        api_url = GREENHOUSE_API_URL.format(slug=slug)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            data = response.json()
            jobs = data.get("jobs", [])
            logger.info(
                "greenhouse_jobs_fetched",
                company=company.name,
                count=len(jobs),
            )
            return jobs  # type: ignore[no-any-return]
