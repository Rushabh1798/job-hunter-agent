"""Tests for jobs scraper agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from job_hunter_agents.agents.jobs_scraper import JobsScraperAgent
from job_hunter_core.models.company import ATSType, CareerPage, Company
from job_hunter_core.models.run import RunConfig
from job_hunter_core.state import PipelineState
from tests.mocks.mock_settings import make_settings


def _make_company(
    name: str = "TestCo",
    ats_type: ATSType = ATSType.UNKNOWN,
    strategy: str = "crawl4ai",
) -> Company:
    """Create test company."""
    return Company(
        name=name,
        domain="testco.com",
        career_page=CareerPage(
            url="https://testco.com/careers",
            ats_type=ats_type,
            scrape_strategy=strategy,
        ),
    )


@pytest.mark.unit
class TestJobsScraperAgent:
    """Test JobsScraperAgent."""

    @pytest.mark.asyncio
    async def test_scrapes_via_crawler(self) -> None:
        """Crawl4ai strategy creates RawJob with HTML content."""
        settings = make_settings(max_concurrent_scrapers=2)
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="test",
            )
        )
        state.companies = [_make_company()]

        with patch("job_hunter_agents.agents.jobs_scraper.create_page_scraper") as mock_scraper_cls:
            mock_scraper = mock_scraper_cls.return_value
            mock_scraper.fetch_page = AsyncMock(return_value="<html>jobs</html>")

            agent = JobsScraperAgent(settings)
            result = await agent.run(state)

        assert len(result.raw_jobs) == 1
        assert result.raw_jobs[0].raw_html == "<html>jobs</html>"

    @pytest.mark.asyncio
    async def test_handles_scrape_error(self) -> None:
        """Scrape error is recorded but does not crash the pipeline."""
        settings = make_settings(max_concurrent_scrapers=2)
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="test",
            )
        )
        state.companies = [_make_company()]

        with patch("job_hunter_agents.agents.jobs_scraper.create_page_scraper") as mock_scraper_cls:
            mock_scraper = mock_scraper_cls.return_value
            mock_scraper.fetch_page = AsyncMock(side_effect=RuntimeError("Connection failed"))

            agent = JobsScraperAgent(settings)
            result = await agent.run(state)

        assert len(result.raw_jobs) == 0
        assert len(result.errors) >= 1

    @pytest.mark.asyncio
    async def test_multiple_companies(self) -> None:
        """Agent scrapes multiple companies concurrently."""
        settings = make_settings(max_concurrent_scrapers=2)
        state = PipelineState(
            config=RunConfig(
                resume_path=Path("/tmp/test.pdf"),
                preferences_text="test",
            )
        )
        state.companies = [
            _make_company("CompA"),
            _make_company("CompB"),
        ]

        with patch("job_hunter_agents.agents.jobs_scraper.create_page_scraper") as mock_scraper_cls:
            mock_scraper = mock_scraper_cls.return_value
            mock_scraper.fetch_page = AsyncMock(return_value="<html>jobs</html>")

            agent = JobsScraperAgent(settings)
            result = await agent.run(state)

        assert len(result.raw_jobs) == 2
