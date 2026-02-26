"""Abstract page scraper interface."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PageScraper(Protocol):
    """Abstract interface for web page scraping providers."""

    async def fetch_page(self, url: str) -> str:
        """Fetch page content (handles JS rendering)."""
        ...

    async def fetch_page_playwright(self, url: str) -> str:
        """Fetch page content using Playwright directly."""
        ...

    async def fetch_json_api(
        self, url: str, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Direct HTTP fetch for JSON APIs."""
        ...
