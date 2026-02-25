"""Web search tool using Tavily API."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from tavily import TavilyClient

logger = structlog.get_logger()


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    content: str
    score: float


class WebSearchTool:
    """Web search using Tavily API."""

    def __init__(self, api_key: str) -> None:
        """Initialize with Tavily API key."""
        self._client = TavilyClient(api_key=api_key)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Perform a web search and return results."""
        import asyncio

        def _search() -> list[SearchResult]:
            response = self._client.search(query=query, max_results=max_results)
            results: list[SearchResult] = []
            for item in response.get("results", []):
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        content=item.get("content", ""),
                        score=item.get("score", 0.0),
                    )
                )
            return results

        return await asyncio.to_thread(_search)

    async def find_career_page(self, company_name: str) -> str | None:
        """Search for a company's official career page URL."""
        query = f"{company_name} careers jobs official site"
        results = await self.search(query, max_results=5)

        for result in results:
            url_lower = result.url.lower()
            if any(kw in url_lower for kw in ["career", "jobs", "hiring", "work"]):
                logger.info("career_page_found", company=company_name, url=result.url)
                return result.url

        if results:
            return results[0].url

        logger.warning("career_page_not_found", company=company_name)
        return None

    async def search_jobs_on_site(
        self, domain: str, role_query: str, max_results: int = 10
    ) -> list[SearchResult]:
        """Search for specific job roles on a company's site."""
        query = f"site:{domain} {role_query} careers jobs"
        return await self.search(query, max_results=max_results)
