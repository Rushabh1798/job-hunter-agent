"""Extended ATS probing — try alternate slugs for companies that failed."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Companies that failed with auto-generated slugs — try common alternate slugs
ALTERNATE_SLUGS = {
    "Hasura": ["hasura", "hasurahq", "hasura-io"],
    "Razorpay": ["razorpay", "razorpaysoftware", "razorpay-software"],
    "Atlassian": ["atlassian", "atlassiancorp"],
    "Uber": ["uber", "uberinc", "ubertechnologies", "uber-technologies"],
    "Freshworks": ["freshworks", "freshworksinc", "freshdesk"],
    "Swiggy": ["swiggy", "bundltech", "bundl-technologies"],
    "Flipkart": ["flipkart", "flipkartcom"],
    "Zomato": ["zomato", "zomatoinc"],
    "Cred": ["cred", "credclub", "cred-club"],
}


async def probe_slug(slug: str) -> tuple[str, str, int] | None:
    """Try a single slug across all 3 ATS platforms."""
    import httpx

    templates = [
        ("greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
        ("lever", f"https://api.lever.co/v0/postings/{slug}"),
        ("ashby", f"https://api.ashbyhq.com/posting-api/job-board/{slug}"),
    ]

    async with httpx.AsyncClient(timeout=8.0) as client:
        for ats_name, url in templates:
            if "greenhouse" in url:
                url = f"{url}?content=true"
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                jobs = data.get("jobs", data) if isinstance(data, dict) else data
                if isinstance(jobs, list) and jobs:
                    return (ats_name, slug, len(jobs))
            except Exception:
                continue
    return None


async def main() -> None:
    """Test alternate slugs for missed companies."""
    print("=== EXTENDED ATS PROBING TEST ===\n")

    for company, slugs in ALTERNATE_SLUGS.items():
        results = await asyncio.gather(*[probe_slug(s) for s in slugs])
        found = [r for r in results if r is not None]

        if found:
            ats, slug, count = found[0]
            print(f"  {company:<20s} -> FOUND on {ats} (slug: {slug}, {count} jobs)")
        else:
            print(f"  {company:<20s} -> NOT FOUND (tried: {', '.join(slugs)})")

    # Also try some India-focused companies that might use ATS boards
    print("\n--- Extra India Companies ---")
    extra = [
        ("Meesho", ["meesho"]),
        ("Groww", ["groww"]),
        ("Dream11", ["dream11", "dreamsports"]),
        ("Zerodha", ["zerodha"]),
        ("Paytm", ["paytm"]),
        ("Ola", ["ola", "olacabs"]),
        ("InMobi", ["inmobi"]),
        ("Zoho", ["zoho", "zohocorp"]),
        ("MakeMyTrip", ["makemytrip"]),
        ("Myntra", ["myntra"]),
        ("BrowserStack", ["browserstack"]),
        ("Chargebee", ["chargebee"]),
        ("Druva", ["druva"]),
        ("Hasura", ["hasura"]),
        ("Razorpay", ["razorpay"]),
        ("Nilenso", ["nilenso"]),
        ("Thoughtspot", ["thoughtspot"]),
        ("Turing", ["turing"]),
        ("ShareChat", ["sharechat"]),
        ("Sprinklr", ["sprinklr"]),
    ]

    for company, slugs in extra:
        results = await asyncio.gather(*[probe_slug(s) for s in slugs])
        found = [r for r in results if r is not None]

        if found:
            ats, slug, count = found[0]
            print(f"  {company:<20s} -> FOUND on {ats} (slug: {slug}, {count} jobs)")
        else:
            print(f"  {company:<20s} -> NOT FOUND")

    print("\n=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
