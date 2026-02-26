"""Factory functions for creating tool instances from settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from job_hunter_core.interfaces.scraper import PageScraper
from job_hunter_core.interfaces.search import SearchProvider

if TYPE_CHECKING:
    from job_hunter_core.config.settings import Settings


def create_search_provider(settings: Settings) -> SearchProvider:
    """Create a search provider based on settings.

    Returns ``DuckDuckGoSearchTool`` when ``settings.search_provider == "duckduckgo"``,
    otherwise returns ``WebSearchTool`` backed by the Tavily API.
    """
    if settings.search_provider == "duckduckgo":
        from job_hunter_agents.tools.duckduckgo_search import DuckDuckGoSearchTool

        return DuckDuckGoSearchTool()

    from job_hunter_agents.tools.web_search import WebSearchTool

    return WebSearchTool(api_key=settings.tavily_api_key.get_secret_value())


def create_page_scraper() -> PageScraper:
    """Create the default page scraper (crawl4ai + Playwright fallback)."""
    from job_hunter_agents.tools.browser import WebScraper

    return WebScraper()
