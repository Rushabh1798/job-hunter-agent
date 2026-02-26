"""Job processing/normalization prompt template (v1)."""

from __future__ import annotations

JOB_PROCESSOR_SYSTEM = """\
You are a job listing parser. Extract structured job information from raw HTML or \
text content of job postings.

<rules>
- Extract the exact job title as written
- Parse salary ranges if mentioned (convert to integers, keep original currency)
- Identify remote_type from location and description: "remote", "hybrid", "onsite", "unknown"
- Extract required vs preferred skills separately
- Do NOT infer posted_date — only extract if explicitly stated
- If salary is in a non-USD currency, note the currency code (INR, EUR, GBP, etc.)
- For seniority_level, infer from title and requirements
- Set is_valid_posting=false if the content is a career landing page, company overview, \
or lists many jobs without specific details for one position. A valid posting has ONE \
specific job title, a description of responsibilities, and requirements for that role.
</rules>
"""

JOB_PROCESSOR_USER = """\
<company_name>{company_name}</company_name>
<source_url>{source_url}</source_url>

<raw_content>
{raw_content}
</raw_content>

Parse this job posting and extract all structured fields.
"""
