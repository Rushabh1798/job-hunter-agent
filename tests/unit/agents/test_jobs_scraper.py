"""Tests for jobs scraper agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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

        with (
            patch("job_hunter_agents.agents.jobs_scraper.create_page_scraper") as mock_scraper_cls,
            patch.object(JobsScraperAgent, "_search_job_links", return_value=[]),
            patch.object(JobsScraperAgent, "_probe_ats_boards", return_value=[]),
        ):
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

        with (
            patch("job_hunter_agents.agents.jobs_scraper.create_page_scraper") as mock_scraper_cls,
            patch.object(JobsScraperAgent, "_search_job_links", return_value=[]),
            patch.object(JobsScraperAgent, "_probe_ats_boards", return_value=[]),
        ):
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

        async def _no_ats(company: object, links: object) -> tuple[list[object], object]:
            return ([], links)

        with (
            patch("job_hunter_agents.agents.jobs_scraper.create_page_scraper") as mock_scraper_cls,
            patch.object(JobsScraperAgent, "_try_ats_boards", side_effect=_no_ats),
        ):
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

        async def _no_ats(company: object, links: object) -> tuple[list[object], object]:
            return ([], links)

        with (
            patch("job_hunter_agents.agents.jobs_scraper.create_page_scraper") as mock_scraper_cls,
            patch.object(JobsScraperAgent, "_try_ats_boards", side_effect=_no_ats),
        ):
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


@pytest.mark.unit
class TestATSBoardDetection:
    """Test ATS board URL detection and company name matching."""

    def test_detect_greenhouse_board(self) -> None:
        """Detects Greenhouse board URL and extracts slug."""
        from job_hunter_agents.agents.jobs_scraper import _detect_ats_board

        result = _detect_ats_board("https://boards.greenhouse.io/stripe/jobs/123")
        assert result is not None
        assert result[0] == "greenhouse"
        assert result[1] == "stripe"

    def test_detect_lever_board(self) -> None:
        """Detects Lever board URL and extracts slug."""
        from job_hunter_agents.agents.jobs_scraper import _detect_ats_board

        result = _detect_ats_board("https://jobs.lever.co/truetandem/abc-123")
        assert result is not None
        assert result[0] == "lever"
        assert result[1] == "truetandem"

    def test_detect_ashby_board(self) -> None:
        """Detects Ashby board URL and extracts slug."""
        from job_hunter_agents.agents.jobs_scraper import _detect_ats_board

        result = _detect_ats_board("https://jobs.ashbyhq.com/acme/abc")
        assert result is not None
        assert result[0] == "ashby"
        assert result[1] == "acme"

    def test_no_detection_for_regular_url(self) -> None:
        """Regular URLs return None."""
        from job_hunter_agents.agents.jobs_scraper import _detect_ats_board

        assert _detect_ats_board("https://example.com/careers") is None

    def test_company_name_matches_slug(self) -> None:
        """Company name matching works for various formats."""
        from job_hunter_agents.agents.jobs_scraper import _company_name_matches_slug

        # Exact matches
        assert _company_name_matches_slug("Stripe", "stripe")
        assert _company_name_matches_slug("TrueTandem", "truetandem")
        assert _company_name_matches_slug("Tiger Analytics", "tigeranalytics")
        # First word match
        assert _company_name_matches_slug("NVIDIA India", "nvidia")
        assert _company_name_matches_slug("Acme Corp", "acme")
        # Exact single word
        assert _company_name_matches_slug("Razorpay", "razorpay")
        # Wrong company (false positives must be rejected)
        assert not _company_name_matches_slug("Flipkart", "ilitch")
        assert not _company_name_matches_slug("Flipkart", "pcom")
        assert not _company_name_matches_slug("Meta", "metabase")


@pytest.mark.unit
class TestScrapeViaApi:
    """Test the _scrape_via_api method."""

    @pytest.mark.asyncio
    async def test_api_strategy_uses_ats_client(self) -> None:
        """API strategy dispatches to the correct ATS client."""
        settings = make_settings(max_concurrent_scrapers=2)
        state = _make_state()
        company = _make_company("GreenhouseCo", ATSType.GREENHOUSE, "api")
        state.companies = [company]

        fake_job: dict[str, Any] = {"id": 1, "title": "SWE", "content": "Build stuff"}

        with patch("job_hunter_agents.agents.jobs_scraper.GreenhouseClient") as mock_gh:
            mock_client = mock_gh.return_value
            mock_client.fetch_jobs = AsyncMock(return_value=[fake_job])

            agent = JobsScraperAgent(settings)
            result = await agent.run(state)

        assert len(result.raw_jobs) == 1
        assert result.raw_jobs[0].raw_json == fake_job
        assert result.raw_jobs[0].scrape_strategy == "api"

    @pytest.mark.asyncio
    async def test_unknown_ats_falls_back_to_crawler(self) -> None:
        """API strategy with unknown ATS falls back to crawler."""
        settings = make_settings(max_concurrent_scrapers=2)
        state = _make_state()
        company = _make_company("UnknownCo", ATSType.UNKNOWN, "api")
        state.companies = [company]

        with (
            patch("job_hunter_agents.agents.jobs_scraper.create_page_scraper") as mock_sc,
            patch.object(JobsScraperAgent, "_search_job_links", return_value=[]),
            patch.object(JobsScraperAgent, "_probe_ats_boards", return_value=[]),
        ):
            mock_sc.return_value.fetch_page = AsyncMock(return_value=_CAREER_HTML_NO_LINKS)
            agent = JobsScraperAgent(settings)
            result = await agent.run(state)

        # Falls back to crawler path → landing page as single RawJob
        assert len(result.raw_jobs) == 1


@pytest.mark.unit
class TestProbeATSBoards:
    """Test _probe_ats_boards method."""

    @pytest.mark.asyncio
    async def test_probe_returns_jobs_on_success(self) -> None:
        """Probing ATS boards returns structured jobs when found."""
        settings = make_settings(max_concurrent_scrapers=2)
        agent = JobsScraperAgent(settings)
        company = _make_company("TestCo")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "jobs": [{"id": 1, "title": "SWE"}, {"id": 2, "title": "PM"}]
        }

        with patch("job_hunter_agents.agents.jobs_scraper.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)

            jobs = await agent._probe_ats_boards(company)

        assert len(jobs) == 2
        assert all(j.scrape_strategy == "api" for j in jobs)

    @pytest.mark.asyncio
    async def test_probe_returns_empty_on_404(self) -> None:
        """Probing returns empty when all ATS APIs return non-200."""
        settings = make_settings(max_concurrent_scrapers=2)
        agent = JobsScraperAgent(settings)
        company = _make_company("NoBoard")

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("job_hunter_agents.agents.jobs_scraper.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)

            jobs = await agent._probe_ats_boards(company)

        assert jobs == []

    @pytest.mark.asyncio
    async def test_probe_handles_exception(self) -> None:
        """Probing handles network errors gracefully."""
        settings = make_settings(max_concurrent_scrapers=2)
        agent = JobsScraperAgent(settings)
        company = _make_company("ErrorCo")

        with patch("job_hunter_agents.agents.jobs_scraper.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(side_effect=RuntimeError("Network error"))

            jobs = await agent._probe_ats_boards(company)

        assert jobs == []


@pytest.mark.unit
class TestTryATSBoards:
    """Test _try_ats_boards method."""

    @pytest.mark.asyncio
    async def test_routes_greenhouse_links_to_api(self) -> None:
        """Greenhouse board URLs are routed through the API."""
        settings = make_settings(max_concurrent_scrapers=2)
        agent = JobsScraperAgent(settings)
        company = _make_company("TestCo")

        links = [
            "https://boards.greenhouse.io/testco/jobs/123",
            "https://testco.com/jobs/456",
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"jobs": [{"id": 1, "title": "SWE"}]}

        with patch("job_hunter_agents.agents.jobs_scraper.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)

            api_jobs, remaining = await agent._try_ats_boards(company, links)

        assert len(api_jobs) >= 1
        assert "https://testco.com/jobs/456" in remaining

    @pytest.mark.asyncio
    async def test_workday_links_skipped(self) -> None:
        """Workday URLs are skipped (no public API)."""
        settings = make_settings(max_concurrent_scrapers=2)
        agent = JobsScraperAgent(settings)
        company = _make_company("TestCo")

        links = [
            "https://acme.wd5.myworkdayjobs.com/en-US/job/swe",
            "https://testco.com/jobs/456",
        ]

        api_jobs, remaining = await agent._try_ats_boards(company, links)

        assert len(api_jobs) == 0
        assert "https://testco.com/jobs/456" in remaining

    @pytest.mark.asyncio
    async def test_no_ats_links_returns_all_remaining(self) -> None:
        """Non-ATS links all go to remaining."""
        settings = make_settings(max_concurrent_scrapers=2)
        agent = JobsScraperAgent(settings)
        company = _make_company("TestCo")

        links = ["https://testco.com/jobs/1", "https://testco.com/jobs/2"]
        api_jobs, remaining = await agent._try_ats_boards(company, links)

        assert api_jobs == []
        assert remaining == links


@pytest.mark.unit
class TestSearchJobLinks:
    """Test _search_job_links method."""

    @pytest.mark.asyncio
    async def test_returns_links_from_search(self) -> None:
        """Search finds job links on ATS platforms."""
        from job_hunter_core.interfaces.search import SearchResult

        settings = make_settings(max_concurrent_scrapers=2)
        agent = JobsScraperAgent(settings)
        company = _make_company("TestCo")
        state = _make_state()

        mock_results = [
            SearchResult(
                title="SWE at TestCo",
                url="https://boards.greenhouse.io/testco/jobs/123",
                content="Apply now",
                score=0.0,
            ),
        ]

        with patch("job_hunter_agents.agents.jobs_scraper.create_search_provider") as mock_sp:
            mock_provider = mock_sp.return_value
            mock_provider.search = AsyncMock(return_value=mock_results)

            links = await agent._search_job_links(company, "https://testco.com/careers", state)

        assert len(links) >= 1
        assert any("greenhouse" in u for u in links)

    @pytest.mark.asyncio
    async def test_returns_empty_on_search_failure(self) -> None:
        """Returns empty list when search provider fails."""
        settings = make_settings(max_concurrent_scrapers=2)
        agent = JobsScraperAgent(settings)
        company = _make_company("TestCo")
        state = _make_state()

        with patch(
            "job_hunter_agents.agents.jobs_scraper.create_search_provider",
            side_effect=RuntimeError("No search provider"),
        ):
            links = await agent._search_job_links(company, "https://testco.com/careers", state)

        assert links == []

    @pytest.mark.asyncio
    async def test_filters_wrong_company_ats_links(self) -> None:
        """ATS links for different companies are filtered out."""
        from job_hunter_core.interfaces.search import SearchResult

        settings = make_settings(max_concurrent_scrapers=2)
        agent = JobsScraperAgent(settings)
        company = _make_company("TestCo")
        state = _make_state()

        mock_results = [
            SearchResult(
                title="SWE at OtherCo",
                url="https://boards.greenhouse.io/otherco/jobs/123",
                content="Apply now",
                score=0.0,
            ),
        ]

        with patch("job_hunter_agents.agents.jobs_scraper.create_search_provider") as mock_sp:
            mock_provider = mock_sp.return_value
            mock_provider.search = AsyncMock(return_value=mock_results)

            links = await agent._search_job_links(company, "https://testco.com/careers", state)

        # OtherCo doesn't match TestCo → filtered out
        assert len(links) == 0
