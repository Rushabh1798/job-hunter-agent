"""Curated seed list of companies with known ATS board slugs.

These companies have been verified to have public Greenhouse, Lever, or Ashby
job boards. The seed list supplements LLM-generated company suggestions to
ensure the pipeline can reliably scrape job data via ATS APIs.

Tags are used to match companies to candidate preferences (industry, location).

Last verified: 2026-02-27 via direct API probing (GET requests).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ATSSeedCompany:
    """A company with a verified ATS board."""

    name: str
    domain: str
    ats: str  # "greenhouse", "lever", "ashby"
    slug: str
    tags: frozenset[str]  # industry/location/size tags for matching


# Verified 2026-02-27 via direct API probing
ATS_SEED_COMPANIES: list[ATSSeedCompany] = [
    # --- Greenhouse ---
    ATSSeedCompany(
        "Stripe",
        "stripe.com",
        "greenhouse",
        "stripe",
        frozenset({"fintech", "payments", "remote", "tier_1"}),
    ),
    ATSSeedCompany(
        "Coinbase",
        "coinbase.com",
        "greenhouse",
        "coinbase",
        frozenset({"crypto", "fintech", "remote", "tier_1"}),
    ),
    ATSSeedCompany(
        "Figma",
        "figma.com",
        "greenhouse",
        "figma",
        frozenset({"design", "saas", "remote", "tier_1"}),
    ),
    ATSSeedCompany(
        "Postman",
        "postman.com",
        "greenhouse",
        "postman",
        frozenset({"devtools", "api", "bangalore", "india", "tier_2"}),
    ),
    ATSSeedCompany(
        "Datadog",
        "datadoghq.com",
        "greenhouse",
        "datadog",
        frozenset({"observability", "devtools", "remote", "tier_1"}),
    ),
    ATSSeedCompany(
        "Cloudflare",
        "cloudflare.com",
        "greenhouse",
        "cloudflare",
        frozenset({"infrastructure", "security", "remote", "tier_1"}),
    ),
    ATSSeedCompany(
        "MongoDB",
        "mongodb.com",
        "greenhouse",
        "mongodb",
        frozenset({"database", "devtools", "remote", "tier_1"}),
    ),
    ATSSeedCompany(
        "Databricks",
        "databricks.com",
        "greenhouse",
        "databricks",
        frozenset({"data", "ai", "ml", "remote", "tier_1"}),
    ),
    ATSSeedCompany(
        "Scale AI",
        "scale.com",
        "greenhouse",
        "scaleai",
        frozenset({"ai", "ml", "data", "remote", "tier_2"}),
    ),
    ATSSeedCompany(
        "Anthropic",
        "anthropic.com",
        "greenhouse",
        "anthropic",
        frozenset({"ai", "ml", "remote", "tier_2"}),
    ),
    ATSSeedCompany(
        "Brex", "brex.com", "greenhouse", "brex", frozenset({"fintech", "remote", "tier_2"})
    ),
    ATSSeedCompany(
        "Gusto",
        "gusto.com",
        "greenhouse",
        "gusto",
        frozenset({"hr", "fintech", "remote", "tier_2"}),
    ),
    ATSSeedCompany(
        "Affirm", "affirm.com", "greenhouse", "affirm", frozenset({"fintech", "remote", "tier_2"})
    ),
    ATSSeedCompany(
        "HubSpot",
        "hubspot.com",
        "greenhouse",
        "hubspot",
        frozenset({"marketing", "saas", "remote", "tier_1"}),
    ),
    ATSSeedCompany(
        "Discord",
        "discord.com",
        "greenhouse",
        "discord",
        frozenset({"social", "gaming", "remote", "tier_2"}),
    ),
    ATSSeedCompany(
        "Samsara",
        "samsara.com",
        "greenhouse",
        "samsara",
        frozenset({"iot", "ai", "remote", "tier_2"}),
    ),
    ATSSeedCompany(
        "GitLab", "gitlab.com", "greenhouse", "gitlab", frozenset({"devtools", "remote", "tier_2"})
    ),
    ATSSeedCompany(
        "Vercel",
        "vercel.com",
        "greenhouse",
        "vercel",
        frozenset({"devtools", "frontend", "remote", "tier_3"}),
    ),
    ATSSeedCompany(
        "Twitch",
        "twitch.tv",
        "greenhouse",
        "twitch",
        frozenset({"streaming", "gaming", "remote", "tier_1"}),
    ),
    ATSSeedCompany(
        "Okta",
        "okta.com",
        "greenhouse",
        "okta",
        frozenset({"security", "identity", "remote", "tier_1"}),
    ),
    ATSSeedCompany(
        "PagerDuty",
        "pagerduty.com",
        "greenhouse",
        "pagerduty",
        frozenset({"devtools", "observability", "remote", "tier_2"}),
    ),
    ATSSeedCompany(
        "Elastic",
        "elastic.co",
        "greenhouse",
        "elastic",
        frozenset({"search", "observability", "remote", "tier_2"}),
    ),
    ATSSeedCompany(
        "Zscaler",
        "zscaler.com",
        "greenhouse",
        "zscaler",
        frozenset({"security", "cloud", "remote", "bangalore", "india", "tier_1"}),
    ),
    ATSSeedCompany(
        "CockroachDB",
        "cockroachlabs.com",
        "greenhouse",
        "cockroachlabs",
        frozenset({"database", "infrastructure", "remote", "tier_3"}),
    ),
    ATSSeedCompany(
        "InMobi",
        "inmobi.com",
        "greenhouse",
        "inmobi",
        frozenset({"adtech", "ai", "bangalore", "india", "tier_2"}),
    ),
    ATSSeedCompany(
        "PhonePe",
        "phonepe.com",
        "greenhouse",
        "phonepe",
        frozenset({"fintech", "payments", "bangalore", "india", "tier_2"}),
    ),
    ATSSeedCompany(
        "Groww",
        "groww.in",
        "greenhouse",
        "groww",
        frozenset({"fintech", "investing", "bangalore", "india", "tier_3"}),
    ),
    ATSSeedCompany(
        "Druva",
        "druva.com",
        "greenhouse",
        "druva",
        frozenset({"cloud", "data", "pune", "india", "tier_2"}),
    ),
    ATSSeedCompany(
        "Turing", "turing.com", "greenhouse", "turing", frozenset({"ai", "remote", "tier_3"})
    ),
    ATSSeedCompany(
        "Rubrik",
        "rubrik.com",
        "greenhouse",
        "rubrik",
        frozenset({"cloud", "data", "security", "bangalore", "india", "tier_2"}),
    ),
    ATSSeedCompany(
        "Tekion",
        "tekion.com",
        "greenhouse",
        "tekion",
        frozenset({"ai", "saas", "bangalore", "india", "tier_3"}),
    ),
    ATSSeedCompany(
        "Razorpay",
        "razorpay.com",
        "greenhouse",
        "razorpaysoftwareprivatelimited",
        frozenset({"fintech", "payments", "bangalore", "india", "tier_2"}),
    ),
    ATSSeedCompany(
        "Commvault",
        "commvault.com",
        "greenhouse",
        "commvault",
        frozenset({"cloud", "data", "hyderabad", "india", "tier_2"}),
    ),
    ATSSeedCompany(
        "Tower Research Capital",
        "tower-research.com",
        "greenhouse",
        "towerresearchcapital",
        frozenset({"fintech", "trading", "gurgaon", "india", "tier_2"}),
    ),
    ATSSeedCompany(
        "IMC Trading",
        "imc.com",
        "greenhouse",
        "imc",
        frozenset({"fintech", "trading", "mumbai", "india", "tier_2"}),
    ),
    # --- Lever ---
    ATSSeedCompany(
        "Cred", "cred.club", "lever", "cred", frozenset({"fintech", "bangalore", "india", "tier_3"})
    ),
    ATSSeedCompany(
        "Meesho",
        "meesho.com",
        "lever",
        "meesho",
        frozenset({"ecommerce", "bangalore", "india", "tier_3"}),
    ),
    ATSSeedCompany(
        "Dream11",
        "dream11.com",
        "lever",
        "dreamsports",
        frozenset({"gaming", "sports", "mumbai", "india", "tier_2"}),
    ),
    ATSSeedCompany(
        "Paytm",
        "paytm.com",
        "lever",
        "paytm",
        frozenset({"fintech", "payments", "noida", "india", "tier_2"}),
    ),
    ATSSeedCompany(
        "Upstox",
        "upstox.com",
        "lever",
        "upstox",
        frozenset({"fintech", "investing", "mumbai", "india", "tier_3"}),
    ),
    ATSSeedCompany(
        "Freshworks",
        "freshworks.com",
        "lever",
        "freshworks",
        frozenset({"saas", "crm", "chennai", "india", "tier_2"}),
    ),  # 0 jobs currently but may reopen
    # --- Ashby (requires User-Agent header — see ashby.py) ---
    ATSSeedCompany(
        "Notion",
        "notion.so",
        "ashby",
        "notion",
        frozenset({"productivity", "saas", "remote", "tier_2"}),
    ),
    ATSSeedCompany(
        "Linear",
        "linear.app",
        "ashby",
        "linear",
        frozenset({"devtools", "saas", "remote", "tier_3"}),
    ),
    ATSSeedCompany(
        "Eleven Labs",
        "elevenlabs.io",
        "ashby",
        "elevenlabs",
        frozenset({"ai", "ml", "audio", "remote", "tier_3"}),
    ),
    ATSSeedCompany(
        "Replit", "replit.com", "ashby", "replit", frozenset({"devtools", "ai", "remote", "tier_3"})
    ),
]


def match_seed_companies(
    *,
    industries: list[str],
    locations: list[str],
    excluded_names: set[str],
    limit: int = 10,
) -> list[ATSSeedCompany]:
    """Select seed companies that best match the candidate's preferences.

    Scores each company by tag overlap with the candidate's industries and
    locations, then returns the top N that aren't in the excluded set.
    """
    industry_tags: set[str] = set()
    for ind in industries:
        for word in ind.lower().split():
            industry_tags.add(word)
    location_tags: set[str] = set()
    for loc in locations:
        for word in loc.lower().split(","):
            location_tags.add(word.strip())

    # Broad matching tags (1x weight)
    query_tags = industry_tags | {"ai", "ml", "remote", "technology"}

    excluded_lower = {n.lower() for n in excluded_names}
    scored: list[tuple[int, ATSSeedCompany]] = []
    for company in ATS_SEED_COMPANIES:
        if company.name.lower() in excluded_lower:
            continue
        overlap = len(company.tags & query_tags)
        # 3x weight for location tags (prioritize local companies)
        loc_overlap = len(company.tags & location_tags)
        overlap += loc_overlap * 2  # +2 extra per location match (3x total)
        scored.append((overlap, company))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:limit]]
