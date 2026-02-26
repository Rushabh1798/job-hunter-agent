"""Public interface re-exports for job_hunter_core."""

from job_hunter_core.interfaces.cache import CacheClient
from job_hunter_core.interfaces.embedder import EmbedderBase
from job_hunter_core.interfaces.scraper import PageScraper
from job_hunter_core.interfaces.search import SearchProvider, SearchResult

__all__ = [
    "CacheClient",
    "EmbedderBase",
    "PageScraper",
    "SearchProvider",
    "SearchResult",
]
