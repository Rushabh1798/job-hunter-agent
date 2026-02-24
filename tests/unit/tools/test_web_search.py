"""Tests for web search tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from job_hunter_agents.tools.web_search import SearchResult, WebSearchTool


@pytest.mark.unit
class TestWebSearchTool:
    """Test WebSearchTool search and career page discovery."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self) -> None:
        """Search returns parsed SearchResult objects."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Stripe Careers",
                    "url": "https://stripe.com/jobs",
                    "content": "Join Stripe",
                    "score": 0.95,
                },
            ]
        }
        with patch(
            "job_hunter_agents.tools.web_search.TavilyClient",
            return_value=mock_client,
        ):
            tool = WebSearchTool(api_key="test-key")
            results = await tool.search("stripe careers")

        assert len(results) == 1
        assert results[0].title == "Stripe Careers"
        assert results[0].url == "https://stripe.com/jobs"
        assert results[0].score == 0.95

    @pytest.mark.asyncio
    async def test_search_empty_results(self) -> None:
        """Search handles empty results gracefully."""
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        with patch(
            "job_hunter_agents.tools.web_search.TavilyClient",
            return_value=mock_client,
        ):
            tool = WebSearchTool(api_key="test-key")
            results = await tool.search("nonexistent company xyz")

        assert results == []

    @pytest.mark.asyncio
    async def test_find_career_page_prefers_career_url(self) -> None:
        """find_career_page prefers URLs containing career keywords."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Stripe Home",
                    "url": "https://stripe.com",
                    "content": "Payments",
                    "score": 0.99,
                },
                {
                    "title": "Stripe Careers",
                    "url": "https://stripe.com/careers",
                    "content": "Join us",
                    "score": 0.90,
                },
            ]
        }
        with patch(
            "job_hunter_agents.tools.web_search.TavilyClient",
            return_value=mock_client,
        ):
            tool = WebSearchTool(api_key="test-key")
            url = await tool.find_career_page("Stripe")

        assert url == "https://stripe.com/careers"

    @pytest.mark.asyncio
    async def test_find_career_page_fallback_first_result(self) -> None:
        """find_career_page falls back to first result if no career keywords."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Acme Inc",
                    "url": "https://acme.com",
                    "content": "About us",
                    "score": 0.80,
                },
            ]
        }
        with patch(
            "job_hunter_agents.tools.web_search.TavilyClient",
            return_value=mock_client,
        ):
            tool = WebSearchTool(api_key="test-key")
            url = await tool.find_career_page("Acme")

        assert url == "https://acme.com"

    @pytest.mark.asyncio
    async def test_find_career_page_no_results(self) -> None:
        """find_career_page returns None when no results found."""
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        with patch(
            "job_hunter_agents.tools.web_search.TavilyClient",
            return_value=mock_client,
        ):
            tool = WebSearchTool(api_key="test-key")
            url = await tool.find_career_page("NonexistentCorp")

        assert url is None

    def test_search_result_dataclass(self) -> None:
        """SearchResult dataclass stores fields correctly."""
        result = SearchResult(
            title="Test",
            url="https://example.com",
            content="body",
            score=0.5,
        )
        assert result.title == "Test"
        assert result.score == 0.5
