"""Abstract search provider interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    content: str
    score: float


@runtime_checkable
class SearchProvider(Protocol):
    """Abstract interface for web search providers."""

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Perform a web search and return results."""
        ...

    async def find_career_page(self, company_name: str) -> str | None:
        """Search for a company's official career page URL."""
        ...

    async def search_jobs_on_site(
        self, domain: str, role_query: str, max_results: int = 10
    ) -> list[SearchResult]:
        """Search for specific job roles on a company's site."""
        ...
