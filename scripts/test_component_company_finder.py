"""Test CompanyFinderAgent in isolation with local_claude."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ["JH_LLM_PROVIDER"] = "local_claude"
os.environ["JH_SEARCH_PROVIDER"] = "duckduckgo"
os.environ["JH_TAVILY_API_KEY"] = "unused"
os.environ["JH_CACHE_BACKEND"] = "db"
os.environ["JH_DB_BACKEND"] = "sqlite"
os.environ["JH_LOG_LEVEL"] = "WARNING"
os.environ["JH_LOG_FORMAT"] = "console"
os.environ.pop("CLAUDECODE", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))


async def main() -> None:
    """Run CompanyFinderAgent with real local_claude."""
    from job_hunter_agents.agents.company_finder import CompanyFinderAgent
    from job_hunter_core.config.settings import Settings
    from job_hunter_core.models.candidate import CandidateProfile, Skill
    from job_hunter_core.models.run import RunConfig
    from job_hunter_core.state import PipelineState

    settings = Settings()  # type: ignore[call-arg]
    settings.db_backend = "sqlite"
    settings.cache_backend = "db"
    settings.search_provider = "duckduckgo"

    profile = CandidateProfile(
        name="Rushabh Thakkar",
        email="rushabh@example.com",
        years_of_experience=5.0,
        skills=[
            Skill(name="Python"),
            Skill(name="Machine Learning"),
            Skill(name="PyTorch"),
            Skill(name="TensorFlow"),
            Skill(name="NLP"),
            Skill(name="AWS"),
        ],
        industries=["Technology", "AI/ML"],
        current_title="Machine Learning Engineer",
        seniority_level="senior",
        tech_stack=["Python", "PyTorch", "TensorFlow", "AWS", "Docker"],
        location="Bangalore, India",
        raw_text="ML engineer with 5 years experience",
        content_hash="a" * 64,
    )

    from job_hunter_core.models.candidate import SearchPreferences

    prefs = SearchPreferences(
        preferred_locations=["Bangalore"],
        remote_preference="any",
        target_titles=["Machine Learning Engineer", "AI Engineer", "ML Engineer"],
        target_seniority=["senior"],
        preferred_industries=["Technology", "AI/ML"],
        currency="INR",
        raw_text="AI ML developer in Bangalore or Remote, 35LPA minimum",
    )

    state = PipelineState(
        config=RunConfig(
            resume_path=Path("/tmp/test.pdf"),
            preferences_text="AI ML developer in Bangalore",
            company_limit=8,
        ),
        profile=profile,
        preferences=prefs,
    )

    print("=== COMPANY FINDER TEST ===")
    print(f"LLM Provider: {settings.llm_provider}")
    print(f"Company limit: {state.config.company_limit}")

    agent = CompanyFinderAgent(settings)
    try:
        result = await agent.run(state)
    except Exception as e:
        print(f"\nFAILED: {type(e).__name__}: {e}")
        return

    print(f"\nCompanies found: {len(result.companies)}")
    print(f"Cost: ${result.total_cost_usd:.4f}")
    print(f"Tokens: {result.total_tokens}")
    print()

    for i, c in enumerate(result.companies, 1):
        ats = c.career_page.ats_type.value if c.career_page else "none"
        url = str(c.career_page.url) if c.career_page else "none"
        tier = c.tier.value if c.tier else "unknown"
        print(f"  {i:2d}. {c.name:<25s} | tier={tier:<8s} | ats={ats:<10s} | url={url}")

    # Check: how many have ATS board URLs vs custom career pages?
    ats_hosts = ["greenhouse.io", "lever.co", "ashbyhq.com"]
    ats_board_count = sum(
        1
        for c in result.companies
        if c.career_page and any(host in str(c.career_page.url) for host in ats_hosts)
    )
    print(f"\nATS board URLs: {ats_board_count}/{len(result.companies)}")
    custom_count = len(result.companies) - ats_board_count
    print(f"Custom career page URLs: {custom_count}/{len(result.companies)}")
    print("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
