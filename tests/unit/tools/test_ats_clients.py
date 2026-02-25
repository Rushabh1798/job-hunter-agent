"""Tests for ATS client detection, slug extraction, and job fetching."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from job_hunter_agents.tools.ats_clients.ashby import AshbyClient
from job_hunter_agents.tools.ats_clients.greenhouse import GreenhouseClient
from job_hunter_agents.tools.ats_clients.lever import LeverClient
from job_hunter_agents.tools.ats_clients.workday import WorkdayClient
from job_hunter_core.models.company import CareerPage, Company


def _make_company(career_url: str) -> Company:
    """Create a company with the given career URL."""
    return Company(
        name="TestCo",
        domain="testco.com",
        career_page=CareerPage(url=career_url),
    )


@pytest.mark.unit
class TestGreenhouseClient:
    """Test Greenhouse ATS detection and fetching."""

    @pytest.mark.asyncio
    async def test_detect_greenhouse_url(self) -> None:
        """Detects Greenhouse board URLs."""
        client = GreenhouseClient()
        assert await client.detect("https://boards.greenhouse.io/stripe") is True

    @pytest.mark.asyncio
    async def test_detect_non_greenhouse(self) -> None:
        """Does not match non-Greenhouse URLs."""
        client = GreenhouseClient()
        assert await client.detect("https://stripe.com/careers") is False

    def test_extract_slug(self) -> None:
        """Extracts slug from Greenhouse URL."""
        client = GreenhouseClient()
        assert client._extract_slug("https://boards.greenhouse.io/stripe") == "stripe"

    def test_extract_slug_no_match(self) -> None:
        """Returns None for non-Greenhouse URL."""
        client = GreenhouseClient()
        assert client._extract_slug("https://example.com") is None

    @pytest.mark.asyncio
    async def test_fetch_jobs_success(self) -> None:
        """fetch_jobs returns job list from Greenhouse API."""
        client = GreenhouseClient()
        company = _make_company("https://boards.greenhouse.io/stripe")

        mock_response = MagicMock()
        mock_response.json.return_value = {"jobs": [{"title": "SWE"}, {"title": "PM"}]}
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_http):
            jobs = await client.fetch_jobs(company)

        assert len(jobs) == 2
        assert jobs[0]["title"] == "SWE"

    @pytest.mark.asyncio
    async def test_fetch_jobs_no_slug(self) -> None:
        """fetch_jobs returns empty when slug can't be extracted."""
        client = GreenhouseClient()
        company = _make_company("https://example.com/careers")

        jobs = await client.fetch_jobs(company)
        assert jobs == []


@pytest.mark.unit
class TestLeverClient:
    """Test Lever ATS detection and fetching."""

    @pytest.mark.asyncio
    async def test_detect_lever_url(self) -> None:
        """Detects Lever URLs."""
        client = LeverClient()
        assert await client.detect("https://jobs.lever.co/figma") is True

    @pytest.mark.asyncio
    async def test_detect_non_lever(self) -> None:
        """Does not match non-Lever URLs."""
        client = LeverClient()
        assert await client.detect("https://figma.com/careers") is False

    def test_extract_slug(self) -> None:
        """Extracts slug from Lever URL."""
        client = LeverClient()
        assert client._extract_slug("https://jobs.lever.co/figma") == "figma"

    def test_extract_slug_no_match(self) -> None:
        """Returns None for non-Lever URL."""
        client = LeverClient()
        assert client._extract_slug("https://example.com") is None

    @pytest.mark.asyncio
    async def test_fetch_jobs_success(self) -> None:
        """fetch_jobs returns job list from Lever API."""
        client = LeverClient()
        company = _make_company("https://jobs.lever.co/figma")

        mock_response = MagicMock()
        mock_response.json.return_value = [{"text": "Engineer"}, {"text": "Designer"}]
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_http):
            jobs = await client.fetch_jobs(company)

        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_fetch_jobs_no_slug(self) -> None:
        """fetch_jobs returns empty when slug can't be extracted."""
        client = LeverClient()
        company = _make_company("https://example.com/careers")

        jobs = await client.fetch_jobs(company)
        assert jobs == []


@pytest.mark.unit
class TestAshbyClient:
    """Test Ashby ATS detection and fetching."""

    @pytest.mark.asyncio
    async def test_detect_ashby_url(self) -> None:
        """Detects Ashby URLs."""
        client = AshbyClient()
        assert await client.detect("https://jobs.ashbyhq.com/notion") is True

    @pytest.mark.asyncio
    async def test_detect_non_ashby(self) -> None:
        """Does not match non-Ashby URLs."""
        client = AshbyClient()
        assert await client.detect("https://notion.so/careers") is False

    def test_extract_slug(self) -> None:
        """Extracts slug from Ashby URL."""
        client = AshbyClient()
        assert client._extract_slug("https://jobs.ashbyhq.com/notion") == "notion"

    def test_extract_slug_no_match(self) -> None:
        """Returns None for non-Ashby URL."""
        client = AshbyClient()
        assert client._extract_slug("https://example.com") is None

    @pytest.mark.asyncio
    async def test_fetch_jobs_success(self) -> None:
        """fetch_jobs returns job list from Ashby API."""
        client = AshbyClient()
        company = _make_company("https://jobs.ashbyhq.com/notion")

        mock_response = MagicMock()
        mock_response.json.return_value = {"jobs": [{"title": "Backend"}]}
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_http):
            jobs = await client.fetch_jobs(company)

        assert len(jobs) == 1
        assert jobs[0]["title"] == "Backend"

    @pytest.mark.asyncio
    async def test_fetch_jobs_no_slug(self) -> None:
        """fetch_jobs returns empty when slug can't be extracted."""
        client = AshbyClient()
        company = _make_company("https://example.com/careers")

        jobs = await client.fetch_jobs(company)
        assert jobs == []


@pytest.mark.unit
class TestWorkdayClient:
    """Test Workday ATS detection and fetching."""

    @pytest.mark.asyncio
    async def test_detect_workday_url(self) -> None:
        """Detects Workday URLs."""
        client = WorkdayClient()
        assert await client.detect("https://company.myworkdayjobs.com/en-US") is True

    @pytest.mark.asyncio
    async def test_detect_non_workday(self) -> None:
        """Does not match non-Workday URLs."""
        client = WorkdayClient()
        assert await client.detect("https://company.com/careers") is False

    @pytest.mark.asyncio
    async def test_fetch_jobs_success(self) -> None:
        """fetch_jobs scrapes page and returns raw content."""
        client = WorkdayClient()
        company = _make_company("https://company.myworkdayjobs.com/en-US/jobs")

        with patch.object(
            client._scraper, "fetch_page", new_callable=AsyncMock, return_value="<html>jobs</html>"
        ):
            jobs = await client.fetch_jobs(company)

        assert len(jobs) == 1
        assert jobs[0]["raw_content"] == "<html>jobs</html>"
        assert "source_url" in jobs[0]

    @pytest.mark.asyncio
    async def test_fetch_jobs_scrape_error(self) -> None:
        """fetch_jobs returns empty list on scrape failure."""
        client = WorkdayClient()
        company = _make_company("https://company.myworkdayjobs.com/en-US/jobs")

        with patch.object(
            client._scraper,
            "fetch_page",
            new_callable=AsyncMock,
            side_effect=RuntimeError("timeout"),
        ):
            jobs = await client.fetch_jobs(company)

        assert jobs == []
