"""Test ATS board probing in isolation — no LLM needed, just HTTP calls."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Companies to test with their expected ATS
TEST_COMPANIES = [
    # (company_name, expected_ats_or_none)
    ("Stripe", "greenhouse"),
    ("LinkedIn", "greenhouse"),
    ("Hasura", "greenhouse"),  # might also be ashby
    ("Razorpay", "greenhouse"),
    ("Postman", "greenhouse"),
    ("Coinbase", "greenhouse"),
    ("Swiggy", None),  # uses custom portal
    ("Flipkart", None),  # uses custom portal
    ("Google", None),  # uses custom portal
    ("Microsoft", None),  # uses custom portal
    ("NVIDIA", None),  # uses Workday
    ("Notion", "greenhouse"),
    ("Figma", "greenhouse"),
    ("Zomato", None),
    ("Atlassian", "greenhouse"),
    ("Uber", "greenhouse"),
    ("Meta", None),
    ("Amazon", None),
    ("Apple", None),
    ("Salesforce", None),
    ("Tiger Analytics", "greenhouse"),
    ("Cred", None),
    ("PhonePe", None),
    ("Freshworks", "greenhouse"),
]


async def probe_company(name: str) -> tuple[str, str | None, str | None, int]:
    """Probe a single company. Returns (name, ats_found, slug_used, job_count)."""
    import httpx

    from job_hunter_agents.tools.ats_clients.ashby import ASHBY_API_URL
    from job_hunter_agents.tools.ats_clients.greenhouse import GREENHOUSE_API_URL
    from job_hunter_agents.tools.ats_clients.lever import LEVER_API_URL

    slug = name.lower().replace(" ", "").replace("-", "")
    first_word = name.lower().split()[0] if name.split() else slug

    api_templates = [
        ("greenhouse", GREENHOUSE_API_URL),
        ("lever", LEVER_API_URL),
        ("ashby", ASHBY_API_URL),
    ]

    async with httpx.AsyncClient(timeout=10.0) as client:
        for slug_candidate in dict.fromkeys([slug, first_word]):
            for ats_name, template in api_templates:
                api_url = template.format(slug=slug_candidate)
                if "greenhouse.io" in api_url:
                    api_url = f"{api_url}?content=true"
                try:
                    resp = await client.get(api_url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    jobs = data.get("jobs", data) if isinstance(data, dict) else data
                    if not isinstance(jobs, list) or not jobs:
                        continue
                    return (name, ats_name, slug_candidate, len(jobs))
                except Exception:
                    continue
    return (name, None, None, 0)


async def main() -> None:
    """Probe all test companies for ATS boards."""
    print("=== ATS BOARD PROBING TEST ===")
    print(f"Testing {len(TEST_COMPANIES)} companies...\n")

    results = await asyncio.gather(*[probe_company(name) for name, _ in TEST_COMPANIES])

    found = 0
    expected_found = 0
    false_negatives: list[str] = []
    surprises: list[str] = []

    print(f"{'Company':<25s} | {'Expected':<12s} | {'Found':<12s} | {'Slug':<20s} | Jobs")
    print("-" * 95)

    for (name, expected), (_, ats_found, slug_used, job_count) in zip(
        TEST_COMPANIES, results, strict=True
    ):
        found_str = ats_found or "NONE"
        expected_str = expected or "none"
        slug_str = slug_used or "-"
        status = ""

        if ats_found:
            found += 1
        if expected:
            expected_found += 1

        if expected and not ats_found:
            status = " <-- MISS"
            false_negatives.append(name)
        elif not expected and ats_found:
            status = " <-- SURPRISE"
            surprises.append(name)
        elif expected and ats_found and expected != ats_found:
            status = f" <-- DIFFERENT (expected {expected})"

        print(
            f"  {name:<23s} | {expected_str:<12s} | {found_str:<12s}"
            f" | {slug_str:<20s} | {job_count:>5d}{status}"
        )

    print("\nSummary:")
    print(f"  Total companies tested: {len(TEST_COMPANIES)}")
    print(f"  ATS boards found: {found}/{len(TEST_COMPANIES)}")
    print(f"  Expected to find: {expected_found}")
    print(f"  False negatives (expected but not found): {false_negatives or 'none'}")
    print(f"  Surprises (found unexpectedly): {surprises or 'none'}")
    print("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
