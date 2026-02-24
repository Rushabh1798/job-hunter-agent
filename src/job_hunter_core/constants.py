"""Shared constants and enums for job-hunter-agent."""

from __future__ import annotations

# Prompt versions — increment when prompt templates change
RESUME_PARSER_PROMPT_VERSION = "v1"
PREFS_PARSER_PROMPT_VERSION = "v1"
COMPANY_FINDER_PROMPT_VERSION = "v1"
JOB_PROCESSOR_PROMPT_VERSION = "v1"
JOB_SCORER_PROMPT_VERSION = "v1"

# LLM token pricing (USD per 1M tokens)
TOKEN_PRICES: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20250514": {"input": 3.00, "output": 15.00},
}

# Common career page paths to try when no ATS is detected
COMMON_CAREER_PATHS = [
    "/careers",
    "/jobs",
    "/work-with-us",
    "/join-us",
    "/open-positions",
    "/career",
    "/hiring",
]

# Static exchange rates (USD base) for salary normalization
EXCHANGE_RATES_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "CAD": 0.74,
    "AUD": 0.65,
    "INR": 0.012,
    "JPY": 0.0067,
    "CHF": 1.13,
    "SGD": 0.75,
    "HKD": 0.13,
}

# Scoring weight dimensions
SCORING_WEIGHTS: dict[str, float] = {
    "skill_match": 0.30,
    "seniority": 0.20,
    "location": 0.15,
    "org_type": 0.15,
    "growth_stage": 0.10,
    "compensation_fit": 0.10,
}

# Rate limiting defaults
DEFAULT_RATE_LIMIT_PER_DOMAIN = 3  # requests per minute
DEFAULT_CONCURRENCY_LIMIT = 5
