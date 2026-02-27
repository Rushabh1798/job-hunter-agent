"""Test JobsScorerAgent with local_claude on real Greenhouse data."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

os.environ["JH_LLM_PROVIDER"] = "local_claude"
os.environ["JH_SEARCH_PROVIDER"] = "duckduckgo"
os.environ["JH_TAVILY_API_KEY"] = "unused"
os.environ["JH_CACHE_BACKEND"] = "db"
os.environ["JH_DB_BACKEND"] = "sqlite"
os.environ["JH_LOG_LEVEL"] = "WARNING"
os.environ["JH_LOG_FORMAT"] = "console"
os.environ.pop("CLAUDECODE", None)

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root))
os.chdir(project_root)


async def fetch_greenhouse_jobs(slug: str, limit: int = 3) -> list[dict[str, Any]]:
    """Fetch real Greenhouse jobs."""
    import httpx

    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        jobs: list[dict[str, Any]] = resp.json().get("jobs", [])
        return jobs[:limit]


async def main() -> None:
    """Test scorer with real data + local_claude."""
    from job_hunter_agents.agents.job_processor import JobProcessorAgent
    from job_hunter_agents.agents.jobs_scorer import JobsScorerAgent
    from job_hunter_core.config.settings import Settings
    from job_hunter_core.models.candidate import CandidateProfile, SearchPreferences, Skill
    from job_hunter_core.models.company import CareerPage, Company, CompanyTier
    from job_hunter_core.models.job import RawJob
    from job_hunter_core.models.run import RunConfig
    from job_hunter_core.state import PipelineState

    settings = Settings()  # type: ignore[call-arg]
    settings.db_backend = "sqlite"
    settings.cache_backend = "db"
    settings.min_score_threshold = 0  # Accept all scores for testing

    print("=== SCORER TEST (local_claude) ===")

    profile = CandidateProfile(
        name="Rushabh Thakkar",
        email="rushabh@example.com",
        years_of_experience=5.0,
        skills=[
            Skill(name="Python", level="expert"),
            Skill(name="Machine Learning", level="advanced"),
            Skill(name="PyTorch", level="advanced"),
            Skill(name="TensorFlow", level="advanced"),
            Skill(name="NLP", level="advanced"),
            Skill(name="AWS", level="intermediate"),
            Skill(name="Docker", level="intermediate"),
        ],
        industries=["Technology", "AI/ML"],
        current_title="Machine Learning Engineer",
        seniority_level="senior",
        tech_stack=["Python", "PyTorch", "TensorFlow", "AWS", "Docker"],
        location="Bangalore, India",
        raw_text="Senior ML engineer",
        content_hash="a" * 64,
    )

    prefs = SearchPreferences(
        preferred_locations=["Bangalore", "Remote"],
        remote_preference="any",
        target_titles=["Machine Learning Engineer", "AI Engineer"],
        target_seniority=["senior"],
        preferred_industries=["Technology"],
        currency="INR",
        raw_text="AI ML developer in Bangalore, 35LPA minimum",
    )

    company_id = uuid4()
    company = Company(
        id=company_id,
        name="Stripe",
        domain="stripe.com",
        career_page=CareerPage(url="https://boards.greenhouse.io/stripe"),
        tier=CompanyTier.TIER_1,
    )

    state = PipelineState(
        config=RunConfig(
            resume_path=Path("/tmp/test.pdf"),
            preferences_text="AI ML developer",
        ),
        profile=profile,
        preferences=prefs,
        companies=[company],
    )

    # Step 1: Fetch real jobs
    print("Fetching Stripe jobs from Greenhouse API...")
    jobs_data = await fetch_greenhouse_jobs("stripe", limit=1)
    print(f"  Fetched {len(jobs_data)} jobs")

    for job_dict in jobs_data:
        state.raw_jobs.append(
            RawJob(
                company_id=company_id,
                company_name="Stripe",
                raw_json=job_dict,
                source_url="https://boards-api.greenhouse.io/v1/boards/stripe/jobs",
                scrape_strategy="api",
                source_confidence=0.95,
            )
        )

    # Step 2: Process (JSON path, no LLM)
    print("Processing jobs (JSON path)...")
    from tests.mocks.mock_settings import make_settings

    processor_settings = make_settings()
    processor = JobProcessorAgent(processor_settings)
    state = await processor.run(state)
    print(f"  Normalized: {len(state.normalized_jobs)} jobs")

    if not state.normalized_jobs:
        print("  NO JOBS NORMALIZED — cannot test scorer")
        return

    # Step 3: Score with local_claude
    print(f"\nScoring {len(state.normalized_jobs)} jobs with local_claude...")
    scorer = JobsScorerAgent(settings)
    try:
        result = await scorer.run(state)
    except Exception as e:
        print(f"\nSCORER FAILED: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return

    print(f"\nScored jobs: {len(result.scored_jobs)}")
    print(f"Cost: ${result.total_cost_usd:.4f}")
    print(f"Tokens: {result.total_tokens}")

    for i, sj in enumerate(result.scored_jobs, 1):
        fr = sj.fit_report
        print(f"\n  {i}. {sj.job.title} (Stripe)")
        print(f"     Score: {fr.score}/100")
        print(f"     Skill overlap: {fr.skill_overlap[:5]}")
        print(f"     Skill gaps: {fr.skill_gaps[:5]}")
        print(f"     Seniority match: {fr.seniority_match}")
        print(f"     Location match: {fr.location_match}")
        print(
            f"     Summary: {fr.summary[:120]}..."
            if fr.summary and len(fr.summary) > 120
            else f"     Summary: {fr.summary}"
        )

    # Verification
    print("\n--- Verification ---")
    all_scored = all(0 <= sj.fit_report.score <= 100 for sj in result.scored_jobs)
    all_have_summary = all(sj.fit_report.summary for sj in result.scored_jobs)
    print(f"  All scores 0-100: {'PASS' if all_scored else 'FAIL'}")
    print(f"  All have summary: {'PASS' if all_have_summary else 'FAIL'}")
    above_80 = sum(1 for sj in result.scored_jobs if sj.fit_report.score >= 80)
    print(f"  Scores >= 80: {above_80}/{len(result.scored_jobs)}")
    print("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
