"""Test JobProcessorAgent with real ATS JSON data (no LLM needed for JSON path)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))


async def fetch_greenhouse_jobs(slug: str, limit: int = 3) -> list[dict[str, Any]]:
    """Fetch real Greenhouse jobs for testing."""
    import httpx

    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        jobs: list[dict[str, Any]] = data.get("jobs", [])
        return jobs[:limit]


async def main() -> None:
    """Test job processor with real Greenhouse JSON data."""
    from job_hunter_agents.agents.job_processor import JobProcessorAgent
    from job_hunter_core.models.job import RawJob
    from job_hunter_core.models.run import RunConfig
    from job_hunter_core.state import PipelineState
    from tests.mocks.mock_settings import make_settings

    print("=== JOB PROCESSOR TEST (JSON path) ===")

    # Fetch real Greenhouse jobs
    test_cases = [
        ("stripe", "Stripe"),
        ("linkedin", "LinkedIn"),
    ]

    settings = make_settings()
    company_id = uuid4()

    state = PipelineState(
        config=RunConfig(
            resume_path=Path("/tmp/test.pdf"),
            preferences_text="test",
        )
    )

    for slug, company_name in test_cases:
        print(f"\nFetching {company_name} ({slug}) jobs from Greenhouse API...")
        try:
            jobs_data = await fetch_greenhouse_jobs(slug, limit=3)
        except Exception as e:
            print(f"  FAILED to fetch: {e}")
            continue

        print(f"  Fetched {len(jobs_data)} jobs")

        for job_dict in jobs_data:
            state.raw_jobs.append(
                RawJob(
                    company_id=company_id,
                    company_name=company_name,
                    raw_json=job_dict,
                    source_url=f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                    scrape_strategy="api",
                    source_confidence=0.95,
                )
            )

    print(f"\nTotal raw jobs: {len(state.raw_jobs)}")
    print("Running JobProcessorAgent (JSON path, no LLM needed)...")

    agent = JobProcessorAgent(settings)
    result = await agent.run(state)

    print(f"\nNormalized jobs: {len(result.normalized_jobs)}")
    print(f"LLM cost: ${result.total_cost_usd:.4f} (should be $0 for JSON path)")

    for i, job in enumerate(result.normalized_jobs, 1):
        print(f"\n  {i}. {job.title}")
        print(f"     Company: {job.company_name}")
        print(f"     Location: {job.location or 'N/A'}")
        apply_url_str = str(job.apply_url)
        print(
            f"     Apply URL: {apply_url_str[:80]}..."
            if len(apply_url_str) > 80
            else f"     Apply URL: {apply_url_str}"
        )
        print(f"     Posted: {job.posted_date or 'N/A'}")
        print(f"     JD length: {len(job.jd_text)} chars")
        print(f"     Hash: {job.content_hash[:16]}...")

    # Verify expectations
    print("\n--- Verification ---")
    all_have_titles = all(j.title for j in result.normalized_jobs)
    all_have_urls = all(j.apply_url for j in result.normalized_jobs)
    any_have_dates = any(j.posted_date for j in result.normalized_jobs)
    any_have_jd = any(len(j.jd_text) > 50 for j in result.normalized_jobs)

    print(f"  All have titles: {'PASS' if all_have_titles else 'FAIL'}")
    print(f"  All have apply URLs: {'PASS' if all_have_urls else 'FAIL'}")
    print(f"  Any have posted dates: {'PASS' if any_have_dates else 'FAIL'}")
    print(f"  Any have JD text (>50 chars): {'PASS' if any_have_jd else 'FAIL'}")
    unique_hashes = {j.content_hash for j in result.normalized_jobs}
    no_dupes = len(unique_hashes) == len(result.normalized_jobs)
    print(f"  No duplicates: {'PASS' if no_dupes else 'FAIL'}")
    print("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
