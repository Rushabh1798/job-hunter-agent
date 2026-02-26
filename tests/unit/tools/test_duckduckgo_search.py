"""Tests for DuckDuckGo search tool helper functions and URL scoring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from job_hunter_agents.tools.duckduckgo_search import (
    DuckDuckGoSearchTool,
    _is_aggregator,
    _is_ats_url,
    _matches_company_domain,
)
from job_hunter_core.interfaces.search import SearchResult


@pytest.mark.unit
class TestAggregatorDetection:
    """Test aggregator URL detection."""

    def test_indeed_is_aggregator(self) -> None:
        """Indeed.com is identified as aggregator."""
        assert _is_aggregator("https://www.indeed.com/jobs/stripe") is True

    def test_linkedin_is_aggregator(self) -> None:
        """LinkedIn is identified as aggregator."""
        assert _is_aggregator("https://linkedin.com/jobs/view/123") is True

    def test_naukri_is_aggregator(self) -> None:
        """Naukri.com is identified as aggregator."""
        assert _is_aggregator("https://www.naukri.com/stripe-jobs") is True

    def test_company_site_is_not_aggregator(self) -> None:
        """Company career page is not an aggregator."""
        assert _is_aggregator("https://stripe.com/careers") is False

    def test_greenhouse_is_not_aggregator(self) -> None:
        """Greenhouse ATS is not an aggregator."""
        assert _is_aggregator("https://boards.greenhouse.io/stripe") is False


@pytest.mark.unit
class TestATSDetection:
    """Test ATS URL detection."""

    def test_greenhouse(self) -> None:
        """Greenhouse.io is detected as ATS."""
        assert _is_ats_url("https://boards.greenhouse.io/stripe/jobs/123") is True

    def test_lever(self) -> None:
        """Lever.co is detected as ATS."""
        assert _is_ats_url("https://jobs.lever.co/stripe/abc-123") is True

    def test_ashby(self) -> None:
        """Ashby is detected as ATS."""
        assert _is_ats_url("https://jobs.ashbyhq.com/stripe") is True

    def test_workday(self) -> None:
        """Workday is detected as ATS."""
        assert _is_ats_url("https://stripe.wd5.myworkdayjobs.com/en-US") is True

    def test_regular_url(self) -> None:
        """Non-ATS URL is not detected."""
        assert _is_ats_url("https://stripe.com/careers") is False


@pytest.mark.unit
class TestCompanyDomainMatch:
    """Test company domain matching."""

    def test_exact_match(self) -> None:
        """Company name in URL."""
        assert _matches_company_domain("https://stripe.com/careers", "Stripe") is True

    def test_multi_word_company(self) -> None:
        """Multi-word company name matching."""
        assert _matches_company_domain("https://databricks.com/careers", "Databricks") is True

    def test_short_word_match(self) -> None:
        """First word of company name matches."""
        assert _matches_company_domain("https://acme.com/careers", "Acme Corp") is True

    def test_no_match(self) -> None:
        """Unrelated URL doesn't match."""
        assert _matches_company_domain("https://indeed.com/jobs", "Stripe") is False


@pytest.mark.unit
class TestPickBestCareerUrl:
    """Test _pick_best_career_url scoring logic."""

    def test_prefers_ats_url(self) -> None:
        """ATS URL is preferred over generic career URL."""
        tool = DuckDuckGoSearchTool()
        results = [
            SearchResult(title="Stripe", url="https://stripe.com", content="", score=0),
            SearchResult(
                title="Stripe Jobs",
                url="https://boards.greenhouse.io/stripe",
                content="",
                score=0,
            ),
        ]
        url = tool._pick_best_career_url(results, "Stripe")
        assert url is not None
        assert "greenhouse.io" in url

    def test_filters_aggregators(self) -> None:
        """Aggregator URLs are excluded."""
        tool = DuckDuckGoSearchTool()
        results = [
            SearchResult(
                title="Stripe on Indeed",
                url="https://indeed.com/jobs/stripe",
                content="",
                score=0,
            ),
            SearchResult(
                title="Stripe Careers",
                url="https://stripe.com/careers",
                content="",
                score=0,
            ),
        ]
        url = tool._pick_best_career_url(results, "Stripe")
        assert url == "https://stripe.com/careers"

    def test_all_aggregators_returns_none(self) -> None:
        """Returns None when all results are aggregators."""
        tool = DuckDuckGoSearchTool()
        results = [
            SearchResult(
                title="Stripe on Indeed",
                url="https://indeed.com/jobs/stripe",
                content="",
                score=0,
            ),
            SearchResult(
                title="Stripe on Glassdoor",
                url="https://glassdoor.com/stripe",
                content="",
                score=0,
            ),
        ]
        url = tool._pick_best_career_url(results, "Stripe")
        assert url is None

    def test_strict_mode_rejects_low_score(self) -> None:
        """Strict mode rejects URLs without career keywords or ATS signals."""
        tool = DuckDuckGoSearchTool()
        results = [
            SearchResult(
                title="Random Article",
                url="https://techblog.example.com/about",
                content="",
                score=0,
            ),
        ]
        url = tool._pick_best_career_url(results, "Acme", strict=True)
        assert url is None

    def test_non_strict_mode_accepts_low_score(self) -> None:
        """Non-strict mode returns best non-aggregator even without keywords."""
        tool = DuckDuckGoSearchTool()
        results = [
            SearchResult(
                title="Acme",
                url="https://acme.com/about",
                content="",
                score=0,
            ),
        ]
        url = tool._pick_best_career_url(results, "Acme", strict=False)
        assert url == "https://acme.com/about"

    def test_empty_results(self) -> None:
        """Returns None for empty results."""
        tool = DuckDuckGoSearchTool()
        assert tool._pick_best_career_url([], "Stripe") is None


@pytest.mark.unit
class TestFindCareerPage:
    """Test the full find_career_page flow with mocked search."""

    @pytest.mark.asyncio
    async def test_finds_career_page_first_query(self) -> None:
        """Returns career page found in first query batch."""
        tool = DuckDuckGoSearchTool()

        async def _mock_search(query: str, max_results: int = 5) -> list[SearchResult]:
            return [
                SearchResult(
                    title="Stripe Careers",
                    url="https://stripe.com/careers",
                    content="Join us",
                    score=0,
                ),
            ]

        with patch.object(tool, "search", side_effect=_mock_search):
            url = await tool.find_career_page("Stripe")

        assert url == "https://stripe.com/careers"

    @pytest.mark.asyncio
    async def test_returns_none_no_results(self) -> None:
        """Returns None when no search results at all."""
        tool = DuckDuckGoSearchTool()

        with patch.object(tool, "search", new_callable=AsyncMock, return_value=[]):
            url = await tool.find_career_page("NonexistentCorp")

        assert url is None
