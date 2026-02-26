"""Web search tool using DuckDuckGo (no API key required)."""

from __future__ import annotations

import asyncio

import structlog

from job_hunter_core.interfaces.search import SearchResult

logger = structlog.get_logger()


class DuckDuckGoSearchTool:
    """Free web search using DuckDuckGo — no API key required.

    Intended for integration tests and development. Uses the
    ``ddgs`` library (dev dependency) via ``asyncio.to_thread()``.
    """

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Perform a web search via DuckDuckGo and return results."""
        from ddgs import DDGS

        def _search() -> list[SearchResult]:
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=max_results))
            results: list[SearchResult] = []
            for item in raw:
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("href", ""),
                        content=item.get("body", ""),
                        score=0.0,
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
