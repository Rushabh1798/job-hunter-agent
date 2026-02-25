"""Tests for web scraper tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from job_hunter_agents.tools.browser import WebScraper


@pytest.mark.unit
class TestWebScraper:
    """Test WebScraper fetch methods and fallback chain."""

    @pytest.mark.asyncio
    async def test_fetch_page_crawl4ai_success(self) -> None:
        """fetch_page returns crawl4ai result when successful."""
        scraper = WebScraper()
        with patch.object(scraper, "_fetch_crawl4ai", new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = "# Page Content"
            result = await scraper.fetch_page("https://example.com")

        assert result == "# Page Content"
        mock_crawl.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_page_falls_back_to_playwright(self) -> None:
        """fetch_page falls back to Playwright when crawl4ai fails."""
        scraper = WebScraper()
        with (
            patch.object(
                scraper,
                "_fetch_crawl4ai",
                new_callable=AsyncMock,
                side_effect=RuntimeError("crawl4ai failed"),
            ),
            patch.object(
                scraper,
                "fetch_page_playwright",
                new_callable=AsyncMock,
                return_value="<html>fallback</html>",
            ) as mock_pw,
        ):
            result = await scraper.fetch_page("https://example.com")

        assert result == "<html>fallback</html>"
        mock_pw.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_json_api_success(self) -> None:
        """fetch_json_api returns parsed JSON."""
        scraper = WebScraper()
        mock_response = MagicMock()
        mock_response.json.return_value = {"jobs": [{"title": "SWE"}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch_json_api("https://api.example.com/jobs")

        assert result == {"jobs": [{"title": "SWE"}]}

    @pytest.mark.asyncio
    async def test_fetch_json_api_with_headers(self) -> None:
        """fetch_json_api passes custom headers."""
        scraper = WebScraper()
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await scraper.fetch_json_api(
                "https://api.example.com/jobs",
                headers={"Authorization": "Bearer token"},
            )

        mock_client.get.assert_called_once_with(
            "https://api.example.com/jobs",
            headers={"Authorization": "Bearer token"},
        )

    @pytest.mark.asyncio
    async def test_fetch_crawl4ai_returns_markdown(self) -> None:
        """_fetch_crawl4ai returns markdown from crawl result."""
        scraper = WebScraper()

        mock_result = MagicMock()
        mock_result.markdown = "# Page Title\nContent here"
        mock_result.html = "<h1>Page Title</h1>"

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=None)

        with patch("crawl4ai.AsyncWebCrawler", return_value=mock_crawler):
            result = await scraper._fetch_crawl4ai("https://example.com")

        assert result == "# Page Title\nContent here"

    @pytest.mark.asyncio
    async def test_fetch_crawl4ai_falls_back_to_html(self) -> None:
        """_fetch_crawl4ai returns html when markdown is empty."""
        scraper = WebScraper()

        mock_result = MagicMock()
        mock_result.markdown = ""
        mock_result.html = "<h1>Page Title</h1>"

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=None)

        with patch("crawl4ai.AsyncWebCrawler", return_value=mock_crawler):
            result = await scraper._fetch_crawl4ai("https://example.com")

        assert result == "<h1>Page Title</h1>"

    @pytest.mark.asyncio
    async def test_fetch_crawl4ai_empty_raises(self) -> None:
        """_fetch_crawl4ai raises ValueError when both markdown and html are empty."""
        scraper = WebScraper()

        mock_result = MagicMock()
        mock_result.markdown = ""
        mock_result.html = ""

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=None)

        with patch("crawl4ai.AsyncWebCrawler", return_value=mock_crawler):
            with pytest.raises(ValueError, match="empty content"):
                await scraper._fetch_crawl4ai("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_page_playwright_returns_content(self) -> None:
        """fetch_page_playwright returns page HTML content."""
        scraper = WebScraper()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.content = AsyncMock(return_value="<html><body>Hi</body></html>")

        mock_browser = AsyncMock()
        mock_browser.new_page.return_value = mock_page
        mock_browser.close = AsyncMock()

        mock_chromium = AsyncMock()
        mock_chromium.launch.return_value = mock_browser

        mock_pw = AsyncMock()
        mock_pw.chromium = mock_chromium
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_pw.__aexit__ = AsyncMock(return_value=None)

        with patch("playwright.async_api.async_playwright", return_value=mock_pw):
            result = await scraper.fetch_page_playwright("https://example.com")

        assert result == "<html><body>Hi</body></html>"
        mock_browser.close.assert_called_once()
