# Pipeline Analysis: Why Only 1 of 25 Jobs Pass Scoring

## TL;DR

The pipeline scrapes 1400+ jobs but only 1 scores above 60. Root cause: **location mismatch** (95% of ATS jobs are US-only) combined with **empty job descriptions** (low confidence scores). The pre-filter selects by title relevance but ignores location, sending US-only jobs to an India-based candidate's scorer.

---

## Component-by-Component Analysis

### 1. Resume Parser — WORKING
- Parses 46-53 skills correctly
- Extracts location (Ahmedabad, India), seniority (Senior/Staff), current title (Technical Lead)
- Duration: ~43s with local_claude
- **No issues**

### 2. Prefs Parser — WORKING
- Correctly interprets "AI ML developer in Bangalore or Remote, 35LPA"
- Target titles: AI ML Developer, ML Engineer, AI Engineer (5 variants)
- Location: Bangalore, Remote preference: any, Currency: INR, min_salary: 3,500,000
- Duration: ~14s
- **No issues**

### 3. Company Finder — PARTIALLY WORKING
- Seed companies (50% of slots): Databricks, Scale AI, Anthropic, Eleven Labs — all US-headquartered
- LLM companies (50%): varies by run, often Google DeepMind, Microsoft, Amazon, Meta — also US-headquartered
- **Issue**: Seed selection favors companies tagged `ai`, `ml`, `remote` but doesn't prioritize `india` or `bangalore` tags
- **Fix**: Boost India-tagged seed companies in `match_seed_companies()`. Add weight for location match (2x multiplier).

### 4. Jobs Scraper — WORKING WELL
- ATS-first strategy works: 1471 jobs in 13-17s (Databricks: 747, Scale AI: 172, Anthropic: 449, Eleven Labs: 100)
- Probes Greenhouse/Lever/Ashby boards before crawling
- HTML fallback works for non-ATS companies (landing pages scraped)
- **Issue**: ATS returns ALL global jobs, not location-filtered. Greenhouse/Lever APIs don't support location filtering.
- **Not fixable at scraper level** — filtering must happen downstream in pre-filter.

### 5. Job Processor — PARTIALLY WORKING
- JSON path processing works ($0 cost, instant) for ATS jobs
- HTML processing works for non-ATS jobs (~$0.13 per job via LLM)
- **Issue 1**: `jd_text` is empty for many Greenhouse jobs because the API is called without `?content=true` parameter
- **Issue 2**: `posted_date` is not extracted from ATS JSON (`updated_at`, `createdAt`, `publishedAt` fields ignored)
- **Issue 3**: For HTML jobs, `apply_url` defaults to the career landing page URL instead of the actual apply link

### 6. Relevance Pre-Filter — PARTIALLY WORKING (new)
- Excludes non-engineering titles (Account Executive, Accountant, etc.) — GOOD
- Ranks by keyword relevance (title + skills) — GOOD
- **Issue**: No location filtering. Selects US-only jobs for an India-based candidate.
- **Fix**: Add location score bonus in `_relevance_prefilter()` for jobs matching candidate's preferred location or remote_type == "remote"

### 7. Jobs Scorer — WORKING CORRECTLY
- Scores are honest and well-calibrated
- Best match: Databricks Staff ML Search Engineer, Bengaluru (score 62) — correctly identified as good match
- Location mismatch correctly penalized (SF/NYC/Seattle jobs for India candidate = 30-50 range)
- **Issue**: Empty `jd_text` results in low confidence (0.25-0.35), which drags scores down
- **No scorer logic issue** — the problem is upstream (location filtering + empty JDs)

### 8. Adaptive Pipeline — WORKING
- Discovery loop correctly runs multiple iterations
- Non-fatal step failures handled (continues to next iteration)
- Company exclusion works (doesn't rediscover same companies)
- **Issue**: Agent timeout was 300s, now fixed to 600s. Scorer completes in ~233s with 25 jobs.

---

## Scoring Breakdown for 25 Jobs (Run run_20260227_120744)

| Score | Count | Pattern |
|-------|-------|---------|
| 60-69 | 1 | Databricks Bengaluru (location match) |
| 50-59 | 2 | Databricks SF (skill match, location penalty) |
| 40-49 | 5 | Mixed roles, US locations, some skill match |
| 30-39 | 10 | US-only, empty JD, moderate skill match |
| 20-29 | 5 | Research/fellowship roles, wrong seniority |
| 10-19 | 2 | Technical Writer (role mismatch) |

**Key insight**: The only job scoring above 60 has `location_match: True` (Bengaluru, India). ALL other jobs have `location_match: False`.

---

## Recommended Fixes (Priority Order)

### Fix 1: Location-aware pre-filter (P0, ~30 min)
**File**: `src/job_hunter_agents/agents/jobs_scorer.py` — `_relevance_prefilter()`

Add location scoring:
```python
# Location bonus: +5 for matching location, +3 for remote
if prefs and prefs.preferred_locations:
    loc_lower = (job.location or "").lower()
    for pref_loc in prefs.preferred_locations:
        if pref_loc.lower() in loc_lower:
            score += 5.0
            break
if job.remote_type == "remote":
    score += 3.0
```

### Fix 2: Greenhouse content=true for full JD text (P1, ~15 min)
**File**: `src/job_hunter_agents/tools/ats_clients/greenhouse.py`

Change API URL from:
```python
GREENHOUSE_API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
```
To:
```python
GREENHOUSE_API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
```

This returns full HTML job descriptions in the `content` field.

### Fix 3: Extract posted_date from ATS JSON (P2, ~20 min)
**File**: `src/job_hunter_agents/agents/job_processor.py` — `_process_from_json()`

Add:
```python
# Extract posted date from ATS JSON
posted_date = None
for field in ["updated_at", "created_at", "createdAt", "publishedAt", "date_posted"]:
    raw = data.get(field)
    if raw:
        posted_date = parse_date(raw)
        break
```

### Fix 4: Boost India seed companies (P3, ~15 min)
**File**: `src/job_hunter_agents/data/ats_seed_companies.py` — `match_seed_companies()`

Add 2x weight for location match:
```python
for company in ATS_SEED_COMPANIES:
    overlap = len(company.tags & query_tags)
    # Double-weight location tags
    location_overlap = len(company.tags & location_tags)
    overlap += location_overlap  # 2x weight for location
```

### Fix 5: Wire apply_url extraction for HTML jobs (P4, ~10 min)
**File**: `src/job_hunter_agents/agents/job_processor.py` — `_process_from_html()`

Change:
```python
apply_url=raw_job.source_url,
```
To:
```python
apply_url=extracted.apply_url or str(raw_job.source_url),
```

---

## Expected Impact After Fixes

| Metric | Before | After (estimated) |
|--------|--------|-------------------|
| Location-matched jobs in pre-filter | 1-2 of 25 | 10-15 of 25 |
| Jobs with full JD text | ~20% | ~90% (Greenhouse content=true) |
| Jobs with posted_date | 0% | ~80% (ATS-sourced) |
| Scored jobs above 60 | 1 | 8-15 |
| Output quality (actionable) | Low | High |
