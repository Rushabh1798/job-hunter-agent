"""Web search tool using DuckDuckGo (no API key required)."""

from __future__ import annotations

import asyncio

import structlog

from job_hunter_core.interfaces.search import SearchResult

logger = structlog.get_logger()

# Job aggregator and blog sites to deprioritize — rarely lead to direct apply URLs
_AGGREGATOR_DOMAINS = frozenset(
    {
        # Global aggregators
        "indeed.com",
        "glassdoor.com",
        "linkedin.com",
        "monster.com",
        "ziprecruiter.com",
        "angel.co",
        "wellfound.com",
        "simplyhired.com",
        # India-specific aggregators
        "naukri.com",
        "internshala.com",
        "shine.com",
        "foundit.in",
        "apna.co",
        "instahyre.com",
        "hirist.com",
        "cutshort.io",
        "weekday.works",
        "hirect.in",
        # Blog / news / content sites (not career pages)
        "alexahire.in",
        "placementstore.com",
        "geeksgod.com",
        "tblogqus.com",
        "interviewchacha.com",
        "globalconsultantsreview.com",
        "unstop.com",
        "startup.jobs",
        "ambitionbox.com",
        "payscale.com",
        "comparably.com",
        "levels.fyi",
        "teamblind.com",
        "reddit.com",
        "quora.com",
        "medium.com",
        "wikipedia.org",
        "youtube.com",
        "fishbowlapp.com",
        "analyticsindiamag.com",
        "techgig.com",
        "geeksforgeeks.org",
    }
)

# ATS domains — higher signal for direct career pages
_ATS_DOMAINS = frozenset(
    {
        "greenhouse.io",
        "lever.co",
        "ashbyhq.com",
        "workday.com",
        "myworkdayjobs.com",
        "smartrecruiters.com",
        "icims.com",
    }
)


_NON_CAREER_URL_PATTERNS = frozenset(
    {
        # Path-based patterns
        "/blog/",
        "/blog?",
        "/stories/",
        "/story/",
        "/news/",
        "/press/",
        "/article/",
        "/about-us/",
        "/helpdesk",
        "/ithelpdesk",
        "/support/",
        "/docs/",
        "/documentation/",
        "/research/",
        "/product/",
        "/pricing",
        "/features/",
        "/login",
        "/signup",
        # Subdomain-based patterns (blog.company.com, stories.company.com)
        "://blog.",
        "://stories.",
        "://story.",
        "://news.",
        "://press.",
        "://docs.",
        "://support.",
        "://help.",
        "://ithelpdesk.",
        "://mumvpn.",
        "://vpn.",
    }
)


def _is_non_career_url(url: str) -> bool:
    """Check if a URL is a non-career page (blog, docs, helpdesk, etc.)."""
    url_lower = url.lower()
    return any(pattern in url_lower for pattern in _NON_CAREER_URL_PATTERNS)


def _is_aggregator(url: str) -> bool:
    """Check if a URL belongs to a known job aggregator."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in _AGGREGATOR_DOMAINS)


def _is_ats_url(url: str) -> bool:
    """Check if a URL matches a known ATS platform."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in _ATS_DOMAINS)


def _matches_company_domain(url: str, company_name: str) -> bool:
    """Check if URL contains the company's likely domain."""
    # Normalize: "Acme Corp" -> "acmecorp", "acme"
    normalized = company_name.lower().replace(" ", "").replace("-", "")
    short = company_name.lower().split()[0] if company_name.split() else ""
    url_lower = url.lower()
    return normalized in url_lower or (len(short) >= 3 and short in url_lower)


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
        """Search for a company's official career page URL.

        Uses multi-strategy search with aggregator filtering and
        ATS/company-domain preference scoring. Prioritizes official
        company domains over third-party sites.
        """
        # Strip common suffixes for cleaner search
        clean_name = company_name.strip()
        for suffix in (" India", " Labs", " R&D", " Research", " AI", " Global Tech"):
            if clean_name.endswith(suffix):
                base_name = clean_name[: -len(suffix)].strip()
                break
        else:
            base_name = clean_name

        queries = [
            f"{base_name} careers jobs site:{base_name.lower().replace(' ', '')}.com",
            f'"{clean_name}" careers hiring apply',
            f'"{clean_name}" jobs greenhouse OR lever OR ashby OR workday',
            f"{clean_name} careers jobs official site",
        ]

        all_results: list[SearchResult] = []
        seen_urls: set[str] = set()

        for query in queries:
            results = await self.search(query, max_results=5)
            for r in results:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_results.append(r)

            # If we already found a good candidate, stop early
            best = self._pick_best_career_url(all_results, company_name)
            if best:
                return best

        # Final attempt with all results collected
        return self._pick_best_career_url(all_results, company_name, strict=False)

    def _pick_best_career_url(
        self,
        results: list[SearchResult],
        company_name: str,
        *,
        strict: bool = True,
    ) -> str | None:
        """Score and pick the best career page URL from search results.

        When strict=True, only returns URLs with career/job keywords or
        ATS patterns. When strict=False, returns the best non-aggregator
        result as a fallback.
        """
        scored: list[tuple[float, str]] = []

        for result in results:
            url = result.url
            if _is_aggregator(url):
                continue

            score = 0.0
            url_lower = url.lower()

            # Company domain match — strongest signal (official site)
            if _matches_company_domain(url, company_name):
                score += 5.0

            # ATS URL — high confidence (direct job listings)
            if _is_ats_url(url):
                score += 4.0

            # Career/job keyword in URL
            if any(kw in url_lower for kw in ("career", "jobs", "hiring", "work", "openings")):
                score += 3.0

            # Penalize non-career pages (blog, stories, helpdesk, etc.)
            if _is_non_career_url(url):
                score -= 6.0

            scored.append((score, url))

        if not scored:
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_url = scored[0]

        # In strict mode, only return if there's meaningful signal
        if strict and best_score < 2.0:
            return None

        logger.info(
            "career_page_found",
            company=company_name,
            url=best_url,
            score=best_score,
        )
        return best_url

    async def search_jobs_on_site(
        self, domain: str, role_query: str, max_results: int = 10
    ) -> list[SearchResult]:
        """Search for specific job roles on a company's site."""
        query = f"site:{domain} {role_query} careers jobs"
        return await self.search(query, max_results=max_results)
