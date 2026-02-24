"""Web scraping tool using crawl4ai with Playwright fallback."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


class WebScraper:
    """Primary: crawl4ai. Fallback: raw Playwright."""

    async def fetch_page(self, url: str) -> str:
        """Fetch page content using crawl4ai (handles JS, SPAs, infinite scroll)."""
        try:
            return await self._fetch_crawl4ai(url)
        except Exception as e:
            logger.warning("crawl4ai_failed_falling_back", url=url, error=str(e))
            return await self.fetch_page_playwright(url)

    async def _fetch_crawl4ai(self, url: str) -> str:
        """Fetch with crawl4ai."""
        from crawl4ai import AsyncWebCrawler

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url)
            if result.markdown:
                return str(result.markdown)
            if result.html:
                return str(result.html)
            msg = f"crawl4ai returned empty content for {url}"
            raise ValueError(msg)

    async def fetch_page_playwright(self, url: str) -> str:
        """Fallback: raw Playwright for pages crawl4ai can't handle."""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle", timeout=30000)
                content = await page.content()
                return content
            finally:
                await browser.close()

    async def fetch_json_api(
        self, url: str, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Direct HTTP fetch for ATS JSON APIs (no browser needed)."""
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers or {})
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result
