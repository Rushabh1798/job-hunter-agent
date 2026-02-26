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


def _make_state() -> PipelineState:
    """Create a base pipeline state."""
    return PipelineState(
        config=RunConfig(
            resume_path=Path("/tmp/test.pdf"),
            preferences_text="test",
        )
    )


_CAREER_HTML_WITH_LINKS = """
<html><body>
<h1>Careers at TestCo</h1>
<a href="/jobs/1234">Software Engineer</a>
<a href="/jobs/5678">Product Manager</a>
<a href="/about">About Us</a>
<a href="/blog/post">Blog</a>
<a href="https://boards.greenhouse.io/testco/jobs/9999">Data Scientist</a>
</body></html>
"""

_CAREER_HTML_NO_LINKS = """
<html><body>
<h1>Join Our Team</h1>
<p>We are hiring! Check back later for openings.</p>
<a href="/about">About</a>
<a href="/contact">Contact</a>
</body></html>
"""


@pytest.mark.unit
class TestJobsScraperAgent:
    """Test JobsScraperAgent."""

    @pytest.mark.asyncio
    async def test_scrapes_via_crawler(self) -> None:
        """Crawl4ai strategy creates RawJob with HTML content."""
        settings = make_settings(max_concurrent_scrapers=2)
        state = _make_state()
        state.companies = [_make_company()]

        with patch("job_hunter_agents.agents.jobs_scraper.create_page_scraper") as mock_scraper_cls:
            mock_scraper = mock_scraper_cls.return_value
            mock_scraper.fetch_page = AsyncMock(return_value=_CAREER_HTML_NO_LINKS)

            agent = JobsScraperAgent(settings)
            result = await agent.run(state)

        # No job links found → falls back to landing page as single RawJob
        assert len(result.raw_jobs) == 1
        assert "Join Our Team" in (result.raw_jobs[0].raw_html or "")

    @pytest.mark.asyncio
    async def test_handles_scrape_error(self) -> None:
        """Scrape error is recorded but does not crash the pipeline."""
        settings = make_settings(max_concurrent_scrapers=2)
        state = _make_state()
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
        state = _make_state()
        state.companies = [
            _make_company("CompA"),
            _make_company("CompB"),
        ]

        with patch("job_hunter_agents.agents.jobs_scraper.create_page_scraper") as mock_scraper_cls:
            mock_scraper = mock_scraper_cls.return_value
            mock_scraper.fetch_page = AsyncMock(return_value=_CAREER_HTML_NO_LINKS)

            agent = JobsScraperAgent(settings)
            result = await agent.run(state)

        assert len(result.raw_jobs) == 2

    @pytest.mark.asyncio
    async def test_extracts_job_links_and_fetches_pages(self) -> None:
        """When career page has job links, fetches each individual page."""
        settings = make_settings(max_concurrent_scrapers=2)
        state = _make_state()
        state.companies = [_make_company()]

        call_count = 0

        async def _mock_fetch(url: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call is the landing page
                return _CAREER_HTML_WITH_LINKS
            # Subsequent calls are individual job pages
            return f"<html><body>Job details for {url}</body></html>"

        with patch("job_hunter_agents.agents.jobs_scraper.create_page_scraper") as mock_scraper_cls:
            mock_scraper = mock_scraper_cls.return_value
            mock_scraper.fetch_page = AsyncMock(side_effect=_mock_fetch)

            agent = JobsScraperAgent(settings)
            result = await agent.run(state)

        # 3 job links: /jobs/1234, /jobs/5678, greenhouse.io/testco/jobs/9999
        assert len(result.raw_jobs) == 3
        # Individual job pages should have higher confidence
        assert all(j.source_confidence == 0.85 for j in result.raw_jobs)

    @pytest.mark.asyncio
    async def test_individual_page_failure_doesnt_lose_others(self) -> None:
        """If one job page fetch fails, other pages are still returned."""
        settings = make_settings(max_concurrent_scrapers=2)
        state = _make_state()
        state.companies = [_make_company()]

        call_count = 0

        async def _mock_fetch(url: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _CAREER_HTML_WITH_LINKS
            if call_count == 2:
                raise RuntimeError("Timeout")
            return "<html><body>Job page</body></html>"

        with patch("job_hunter_agents.agents.jobs_scraper.create_page_scraper") as mock_scraper_cls:
            mock_scraper = mock_scraper_cls.return_value
            mock_scraper.fetch_page = AsyncMock(side_effect=_mock_fetch)

            agent = JobsScraperAgent(settings)
            result = await agent.run(state)

        # 1 failed + 2 succeeded = 2 raw jobs
        assert len(result.raw_jobs) == 2


@pytest.mark.unit
class TestExtractJobLinks:
    """Test _extract_job_links static method."""

    def test_extracts_job_urls(self) -> None:
        """Extracts job URLs matching known patterns."""
        links = JobsScraperAgent._extract_job_links(
            _CAREER_HTML_WITH_LINKS,
            "https://testco.com/careers",
        )
        assert len(links) == 3
        assert any("/jobs/1234" in u for u in links)
        assert any("/jobs/5678" in u for u in links)
        assert any("greenhouse.io" in u for u in links)

    def test_filters_non_job_links(self) -> None:
        """Non-job links (about, blog) are excluded."""
        links = JobsScraperAgent._extract_job_links(
            _CAREER_HTML_WITH_LINKS,
            "https://testco.com/careers",
        )
        assert not any("/about" in u for u in links)
        assert not any("/blog" in u for u in links)

    def test_empty_html(self) -> None:
        """Returns empty list for HTML with no job links."""
        links = JobsScraperAgent._extract_job_links(
            "<html><body>No links here</body></html>",
            "https://example.com/careers",
        )
        assert links == []

    def test_deduplicates_links(self) -> None:
        """Duplicate hrefs are deduplicated."""
        html = """
        <a href="/jobs/123">Job A</a>
        <a href="/jobs/123">Job A again</a>
        <a href="/jobs/123#apply">Job A with fragment</a>
        """
        links = JobsScraperAgent._extract_job_links(
            html,
            "https://example.com/careers",
        )
        assert len(links) == 1

    def test_resolves_relative_urls(self) -> None:
        """Relative URLs are resolved against base URL."""
        html = '<a href="/jobs/42">Apply</a>'
        links = JobsScraperAgent._extract_job_links(
            html,
            "https://example.com/careers",
        )
        assert links[0] == "https://example.com/jobs/42"

    def test_skips_base_url(self) -> None:
        """Links pointing back to the base URL are skipped."""
        html = '<a href="/careers">Back to careers</a><a href="/jobs/1">Job</a>'
        links = JobsScraperAgent._extract_job_links(
            html,
            "https://example.com/careers",
        )
        assert len(links) == 1
        assert "/jobs/1" in links[0]

    def test_ats_url_patterns(self) -> None:
        """Matches various ATS URL patterns."""
        html = """
        <a href="https://jobs.lever.co/acme/abc-123">Lever job</a>
        <a href="https://jobs.ashbyhq.com/acme/abc">Ashby job</a>
        <a href="https://acme.wd5.myworkdayjobs.com/en-US/job/swe">Workday job</a>
        """
        links = JobsScraperAgent._extract_job_links(
            html,
            "https://acme.com/careers",
        )
        assert len(links) >= 2

    def test_max_links_limit(self) -> None:
        """Respects the max links per company limit."""
        # Create 25 job links
        hrefs = "".join(f'<a href="/jobs/{i}">Job {i}</a>' for i in range(25))
        html = f"<html><body>{hrefs}</body></html>"
        links = JobsScraperAgent._extract_job_links(
            html,
            "https://example.com/careers",
        )
        assert len(links) == 20
