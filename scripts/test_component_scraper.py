"""Test JobsScraperAgent in isolation — no LLM needed.

Tests the full scrape flow: landing page crawl → link extraction → ATS probing.
Uses companies with KNOWN Greenhouse/Lever/Ashby boards.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ["JH_LLM_PROVIDER"] = "fake"
os.environ["JH_SEARCH_PROVIDER"] = "duckduckgo"
os.environ["JH_TAVILY_API_KEY"] = "unused"
os.environ["JH_CACHE_BACKEND"] = "db"
os.environ["JH_DB_BACKEND"] = "sqlite"
os.environ["JH_LOG_LEVEL"] = "INFO"
os.environ["JH_LOG_FORMAT"] = "console"

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))
os.chdir(project_root)


async def test_single_company(
    company_name: str,
    career_url: str,
    ats_type_str: str,
    strategy: str,
) -> dict[str, Any]:
    """Test scraping a single company. Returns result dict."""
    from job_hunter_core.models.company import ATSType, CareerPage, Company
    from job_hunter_core.models.run import RunConfig
    from job_hunter_core.state import PipelineState
    from tests.mocks.mock_settings import make_settings

    settings = make_settings(max_concurrent_scrapers=2)
    state = PipelineState(
        config=RunConfig(
            resume_path=Path("/tmp/test.pdf"),
            preferences_text="AI ML developer in Bangalore",
        )
    )

    ats_map = {
        "greenhouse": ATSType.GREENHOUSE,
        "lever": ATSType.LEVER,
        "ashby": ATSType.ASHBY,
        "unknown": ATSType.UNKNOWN,
    }

    company = Company(
        name=company_name,
        domain=company_name.lower().replace(" ", "") + ".com",
        career_page=CareerPage(
            url=career_url,
            ats_type=ats_map.get(ats_type_str, ATSType.UNKNOWN),
            scrape_strategy=strategy,
        ),
    )
    state.companies = [company]

    from job_hunter_agents.agents.jobs_scraper import JobsScraperAgent

    agent = JobsScraperAgent(settings)
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(agent.run(state), timeout=60.0)
        elapsed = time.monotonic() - start
        return {
            "company": company_name,
            "raw_jobs": len(result.raw_jobs),
            "json_jobs": sum(1 for j in result.raw_jobs if j.raw_json),
            "html_jobs": sum(1 for j in result.raw_jobs if j.raw_html),
            "elapsed": round(elapsed, 1),
            "status": "OK",
            "sample_source": result.raw_jobs[0].source_url if result.raw_jobs else None,
            "sample_strategy": result.raw_jobs[0].scrape_strategy if result.raw_jobs else None,
        }
    except TimeoutError:
        return {
            "company": company_name,
            "raw_jobs": 0,
            "json_jobs": 0,
            "html_jobs": 0,
            "elapsed": 60.0,
            "status": "TIMEOUT",
            "sample_source": None,
            "sample_strategy": None,
        }
    except Exception as e:
        return {
            "company": company_name,
            "raw_jobs": 0,
            "json_jobs": 0,
            "html_jobs": 0,
            "elapsed": time.monotonic() - start,
            "status": f"ERROR: {type(e).__name__}: {e}",
            "sample_source": None,
            "sample_strategy": None,
        }


async def main() -> None:
    """Test scraping for various company types."""
    print("=== SCRAPER COMPONENT TEST ===\n")

    # Test companies with known ATS boards (should use API strategy → JSON jobs)
    ats_companies = [
        ("Stripe", "https://stripe.com/jobs", "unknown", "crawl4ai"),
        ("Postman", "https://www.postman.com/company/careers/", "unknown", "crawl4ai"),
        ("Coinbase", "https://www.coinbase.com/careers", "unknown", "crawl4ai"),
    ]

    # Test companies with known ATS boards (API strategy — direct)
    api_companies = [
        ("Figma", "https://boards.greenhouse.io/figma", "greenhouse", "api"),
        ("Groww", "https://boards.greenhouse.io/groww", "greenhouse", "api"),
    ]

    # Test companies with SPA career pages (expected to struggle)
    spa_companies = [
        ("Microsoft", "https://careers.microsoft.com/", "unknown", "crawl4ai"),
    ]

    print("--- Known ATS Board Companies (crawl4ai strategy, should probe ATS) ---")
    for name, url, ats, strat in ats_companies:
        result = await test_single_company(name, url, ats, strat)
        status = result["status"]
        print(
            f"  {result['company']:<15s} | {status:<10s} | "
            f"JSON: {result['json_jobs']:>3d} | HTML: {result['html_jobs']:>3d} | "
            f"Total: {result['raw_jobs']:>3d} | {result['elapsed']}s | "
            f"strategy={result['sample_strategy']}"
        )

    print("\n--- Direct API Strategy Companies ---")
    for name, url, ats, strat in api_companies:
        result = await test_single_company(name, url, ats, strat)
        status = result["status"]
        print(
            f"  {result['company']:<15s} | {status:<10s} | "
            f"JSON: {result['json_jobs']:>3d} | HTML: {result['html_jobs']:>3d} | "
            f"Total: {result['raw_jobs']:>3d} | {result['elapsed']}s | "
            f"strategy={result['sample_strategy']}"
        )

    print("\n--- SPA Career Page Companies (expected to struggle) ---")
    for name, url, ats, strat in spa_companies:
        result = await test_single_company(name, url, ats, strat)
        status = result["status"]
        print(
            f"  {result['company']:<15s} | {status:<10s} | "
            f"JSON: {result['json_jobs']:>3d} | HTML: {result['html_jobs']:>3d} | "
            f"Total: {result['raw_jobs']:>3d} | {result['elapsed']}s | "
            f"strategy={result['sample_strategy']}"
        )

    print("\n=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
