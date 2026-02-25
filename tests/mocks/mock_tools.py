"""Named fake tool implementations for dry-run and integration tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class FakePDFParser:
    """Returns pre-extracted resume text from fixture file."""

    async def extract_text(self, path: Path) -> str:
        """Return fixture resume text regardless of input path."""
        fixture = FIXTURES_DIR / "resume_text.txt"
        return fixture.read_text()


class FakeWebSearchTool:
    """Returns fixture search results."""

    def __init__(self, api_key: str = "") -> None:
        """Accept api_key to match real constructor signature."""
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[_FakeSearchResult]:
        """Return fixture search results."""
        fixture = FIXTURES_DIR / "search_results" / "career_page_search.json"
        data = json.loads(fixture.read_text())
        return [
            _FakeSearchResult(
                title=r["title"],
                url=r["url"],
                content=r["content"],
                score=r["score"],
            )
            for r in data["results"][:max_results]
        ]

    async def find_career_page(self, company_name: str) -> str | None:
        """Return the first career URL from fixture data."""
        results = await self.search(f"{company_name} careers")
        for r in results:
            url_lower = r.url.lower()
            if any(kw in url_lower for kw in ["career", "jobs", "hiring", "greenhouse", "lever"]):
                return r.url
        return results[0].url if results else None

    async def search_jobs_on_site(
        self, domain: str, role_query: str, max_results: int = 10
    ) -> list[_FakeSearchResult]:
        """Return fixture search results."""
        return await self.search(f"site:{domain} {role_query}", max_results)


@dataclass
class _FakeSearchResult:
    """Mimics web_search.SearchResult."""

    title: str
    url: str
    content: str
    score: float


class FakeWebScraper:
    """Returns fixture HTML content."""

    async def fetch_page(self, url: str) -> str:
        """Return career page HTML from fixtures."""
        fixture = FIXTURES_DIR / "html" / "career_page.html"
        return fixture.read_text()

    async def fetch_page_playwright(self, url: str) -> str:
        """Return same fixture HTML."""
        return await self.fetch_page(url)

    async def fetch_json_api(
        self, url: str, headers: dict[str, str] | None = None
    ) -> dict[str, object]:
        """Return empty dict (ATS clients handle JSON parsing)."""
        return {}


class FakeGreenhouseClient:
    """Returns fixture Greenhouse job data."""

    async def detect(self, career_url: str) -> bool:
        """Use real regex detection logic."""
        import re

        return bool(re.search(r"boards\.greenhouse\.io/(\w+)", career_url, re.IGNORECASE))

    async def fetch_jobs(self, company: object) -> list[dict[str, object]]:
        """Return fixture Greenhouse jobs."""
        fixture = FIXTURES_DIR / "ats_responses" / "greenhouse_jobs.json"
        data = json.loads(fixture.read_text())
        return data["jobs"]  # type: ignore[no-any-return]


class FakeLeverClient:
    """Returns fixture Lever job data."""

    async def detect(self, career_url: str) -> bool:
        """Use real regex detection logic."""
        import re

        return bool(re.search(r"jobs\.lever\.co/(\w[\w-]*)", career_url, re.IGNORECASE))

    async def fetch_jobs(self, company: object) -> list[dict[str, object]]:
        """Return fixture Lever jobs."""
        fixture = FIXTURES_DIR / "ats_responses" / "lever_jobs.json"
        return json.loads(fixture.read_text())  # type: ignore[no-any-return]


class FakeAshbyClient:
    """Returns fixture Ashby job data."""

    async def detect(self, career_url: str) -> bool:
        """Use real regex detection logic."""
        import re

        return bool(re.search(r"jobs\.ashbyhq\.com/(\w[\w-]*)", career_url, re.IGNORECASE))

    async def fetch_jobs(self, company: object) -> list[dict[str, object]]:
        """Return fixture Ashby jobs."""
        fixture = FIXTURES_DIR / "ats_responses" / "ashby_jobs.json"
        data = json.loads(fixture.read_text())
        return data["jobs"]  # type: ignore[no-any-return]


class FakeWorkdayClient:
    """Returns empty results (Workday is crawl-based)."""

    async def detect(self, career_url: str) -> bool:
        """Use real regex detection logic."""
        import re

        return bool(re.search(r"myworkdayjobs\.com|workday\.com/en-US", career_url, re.IGNORECASE))

    async def fetch_jobs(self, company: object) -> list[dict[str, object]]:
        """Return empty list (Workday has no standard API format)."""
        return []


@dataclass
class _EmailCall:
    """Record of a single send() call for assertion."""

    to_email: str
    subject: str
    html_body: str
    text_body: str
    attachment_path: str | None


class FakeEmailSender:
    """Records calls for assertion instead of sending."""

    def __init__(self, **kwargs: object) -> None:
        """Accept arbitrary kwargs to match real constructor."""
        self.calls: list[_EmailCall] = []

    async def send(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        attachment_path: str | None = None,
    ) -> bool:
        """Record the call and return True."""
        self.calls.append(
            _EmailCall(
                to_email=to_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                attachment_path=attachment_path,
            )
        )
        return True


class FakeEmbedder:
    """Returns deterministic 384-dim vectors."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        """Accept model_name to match real constructor."""
        self._dim = 384

    async def embed_text(self, text: str) -> list[float]:
        """Return deterministic vector based on text hash."""
        import hashlib

        h = hashlib.md5(text.encode()).hexdigest()
        seed = int(h[:8], 16)
        # Deterministic pseudo-random vector
        return [((seed * (i + 1)) % 1000) / 1000.0 for i in range(self._dim)]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embed via individual calls."""
        return [await self.embed_text(t) for t in texts]
