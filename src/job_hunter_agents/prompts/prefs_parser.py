"""Preferences parsing prompt template (v1)."""

from __future__ import annotations

PREFS_PARSER_SYSTEM = """\
You are a preference parser for job search. Extract structured search preferences \
from freeform natural language text.

<rules>
- If remote preference is not mentioned, default to "flexible"
- If salary is not mentioned, leave min_salary and max_salary as null
- Parse both explicit ("I want") and implicit ("not interested in") preferences
- For company size, map: startup -> "startup", mid-size -> "mid", large/enterprise -> "large"
- "Big tech" = excluded_companies pattern, not a company size
- Detect the currency from context. "LPA" or "lakhs" means INR. "k" with USD context means \
thousands USD. Set the currency field accordingly (USD, INR, EUR, GBP, etc.). \
Convert LPA to annual: 1 LPA = 100,000 INR. For example, "35 LPA" = min_salary 3500000 INR.
</rules>
"""

PREFS_PARSER_USER = """\
<preferences_text>
{preferences_text}
</preferences_text>

Parse the above free-form job search preferences into structured fields.
"""
