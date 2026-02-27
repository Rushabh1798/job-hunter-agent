# Pipeline Diagnostic Report

**Date**: 2026-02-27
**Run ID**: `run_20260227_080144`
**Status**: 0 scored jobs across 2 discovery iterations ($0.84 cost, 718s duration)

---

## Executive Summary

The pipeline fails to produce scored jobs due to **5 cascading component failures**. The root causes span from company selection (LLM picks companies with custom SPA career portals) through scraping (crawl4ai can't render JavaScript SPAs) to infrastructure (300s per-agent timeout kills in-progress ATS API results).

The newly added `_probe_ats_boards()` fix proved effective — it successfully discovered **LinkedIn (53 jobs)** and **Stripe (606 jobs)** via Greenhouse API probing. However, these results were **lost** when the scraper timed out waiting for other companies' SPA career pages to crawl.

---

## Component-by-Component Analysis

### 1. Company Finder Agent — PARTIALLY WORKING

**What works:**
- Generates 8 companies per iteration
- Company tiering (tier_1/tier_2/tier_3/startup) present in output
- Preference enrichment from resume is working (locations, target_titles inferred)
- Career URLs provided by LLM for every company (skips DuckDuckGo search)

**What's broken:**
- **LLM picks companies with custom SPA career portals** despite prompt asking for ATS-friendly companies
  - Iteration 0: Google DeepMind, Microsoft, Flipkart, Swiggy, Amazon, Razorpay, Atlassian, Hasura
  - Iteration 1: LinkedIn, NVIDIA, Meta, Stripe, Uber, Salesforce, Apple + 1 more
  - Of these 16 companies, only **LinkedIn** and **Stripe** turned out to have Greenhouse boards (found via `_probe_ats_boards`, not via the LLM's URL)
- **LLM-provided career URLs point to custom portals**, never ATS board URLs:
  - `careers.google.com`, `careers.microsoft.com`, `careers.swiggy.com`, etc.
  - The prompt asks for Greenhouse/Lever/Ashby URLs but the LLM provides custom career page URLs instead

**Root Cause**: The LLM doesn't know which ATS each company uses. It always provides the company's main career page URL, not the ATS board URL (which may not be publicly advertised).

**Fix Plan**:
- **Short-term**: Run `_probe_ats_boards()` FIRST in the scraper (before crawling), not as last resort. This already works for LinkedIn and Stripe, bypassing the need for correct LLM-provided URLs.
- **Medium-term**: Add a static ATS registry mapping known companies to their ATS boards (e.g., `stripe → boards.greenhouse.io/stripe`). Many well-known companies' ATS slugs are discoverable.
- **Long-term**: Prompt the LLM to generate companies in smaller batches (4 at a time) with a hard requirement that at least 50% use Greenhouse/Lever/Ashby.

---

### 2. Jobs Scraper Agent — CRITICAL FAILURE

**What works:**
- `_probe_ats_boards()` successfully probes ATS APIs by company name slug:
  - LinkedIn → Greenhouse (53 jobs)
  - Stripe → Greenhouse (606 jobs, capped at 20)
- `?content=true` parameter on Greenhouse API for full job descriptions
- Company name validation prevents wrong-company ATS matches
- ATS board detection (`_detect_ats_board()`) correctly extracts slugs

**What's broken:**

1. **300s timeout kills ALL results for the step** (CRITICAL)
   - The scraper runs all 8 companies concurrently (semaphore=2)
   - LinkedIn and Stripe ATS probing completes in ~10s
   - But companies with SPA career pages (Meta, NVIDIA, Salesforce, Apple) take 60-300s to crawl and search
   - Apple's career page hits Playwright's 60s timeout, then crawl4ai retry
   - When the 300s per-agent timeout fires, `asyncio.wait_for()` cancels everything
   - The already-completed LinkedIn/Stripe results **are in the state but never checkpointed** because the timeout returns a `RunResult`, not a `PipelineState`
   - In the adaptive pipeline, when `_run_agent_step` returns `RunResult`, it restores `prev_scored` and exits the loop

2. **crawl4ai returns empty content for JavaScript SPAs**
   - NVIDIA (Workday): `content_length=1`
   - Meta, Salesforce, Microsoft, Flipkart, Atlassian: crawl4ai returns HTML but it's a shell (no actual job data rendered)
   - These all fall through to `_search_job_links()` which also fails (see below)

3. **`_probe_ats_boards()` runs too late in the flow**
   - Current order: crawl landing page → extract links → search for links → **probe ATS boards** (last resort) → fall back to landing page
   - ATS probing is fast and reliable (~2s per company) but only runs after crawling + searching fails (30-60s wasted per company)
   - By the time probing runs for company #3-4, the 300s timeout may be close

4. **crawl4ai Playwright crashes at pipeline end**
   - `TargetClosedError: Target page, context or browser has been closed` after pipeline completes
   - Not a data issue but indicates resource cleanup problem with Playwright browser instances

**Fix Plan**:
- **Fix A (Critical)**: Increase `agent_timeout_seconds` for scraper to 600s, OR make scraper save partial results before timeout, OR run ATS probing first (before crawling)
- **Fix B**: Restructure `_scrape_via_crawler()` to probe ATS boards FIRST (not last):
  1. `_probe_ats_boards()` — fast, reliable, returns structured JSON
  2. If probe fails, THEN crawl the landing page
  3. If crawl returns no links, THEN search (which is slow and unreliable)
- **Fix C**: Add per-company timeout (30s) instead of per-step timeout (300s). Companies that timeout are skipped, but already-probed results are preserved.

---

### 3. DuckDuckGo Search — MOSTLY FAILING

**What works:**
- Occasionally finds a real job link (found 1 Amazon job link in iteration 0)
- Non-career URL filtering (`_is_non_career_url()`) correctly rejects blog/story URLs

**What's broken:**
- **Google blocks all requests** (HTTP 429 on every query — "sorry/index" captcha page)
- **Brave blocks all requests** (HTTP 429 on every query)
- **Yandex blocks all requests** (captcha page on every query)
- **DuckDuckGo itself disconnects** (`RemoteProtocolError: Server disconnected`, `ConnectTimeout`)
- **Mojeek blocks some requests** (HTTP 403)
- Only **Yahoo** and **Wikipedia** return 200 consistently, but Wikipedia is useless for job search
- When search finds a result, it can be wrong: Uber search returned a **blog post** (`uber.com/blog/from-predictive-to-generative-ai/`)

**Root Cause**: The DuckDuckGo library (`duckduckgo-search`) internally uses multiple search backends (Google, Brave, DuckDuckGo, Yandex, Mojeek, Yahoo). All of them are rate-limited or blocked when making rapid sequential queries. The pipeline fires 8 companies × 2 queries × 5 results = ~80 search requests in under 30s.

**Fix Plan**:
- **Short-term**: Deprioritize search entirely. Run `_probe_ats_boards()` first — it's deterministic and doesn't need search. Only fall back to search for companies where ATS probing fails AND the career page has no links.
- **Medium-term**: Add rate limiting to DuckDuckGo search (1 query/second instead of burst)
- **Long-term**: Use Tavily API (production search provider with API key, no rate limiting) for real runs

---

### 4. Job Processor Agent — WORKING (but starved of input)

**What works:**
- `is_valid_posting=False` correctly rejects career landing pages (7 landing pages rejected in iteration 0)
- `_process_from_json()` handles ATS JSON with content (Greenhouse `?content=true`)
- Hash-based deduplication working
- `_process_from_html()` correctly extracts fields from real job postings

**What's broken:**
- Nothing structurally wrong — it's just starved of input
- In iteration 0: received 8 raw jobs, all landing pages → 7 rejected as non-job-content, 1 Amazon job normalized
- In iteration 1: never ran (scraper timed out)
- Cost: $0.72 spent on 8 LLM calls to process landing pages that are obviously not job postings

**Fix Plan**:
- **Minor optimization**: Skip LLM call for HTML jobs with content < 500 chars (threshold currently 100, but Workday SPA shells return ~200-400 chars of boilerplate). OR check if content has any of `["job", "engineer", "developer", "apply", "position"]` before calling LLM.
- No structural changes needed. The processor works fine when given real input.

---

### 5. Jobs Scorer Agent — WORKING (but starved of input)

**What works:**
- Scored the 1 Amazon job in iteration 0 (but score was below 80% threshold)
- Recency dimension and calibration rules applied correctly
- Company tier context included in scoring prompt

**What's broken:**
- Only scored 1 job across the entire run
- The single Amazon job scored below `min_score_threshold=80`, so `above_threshold=0`

**Fix Plan**:
- No changes needed. The scorer works correctly — it just needs more input.
- Consider lowering `min_score_threshold` to 70 for the initial run to get some results while debugging.

---

### 6. Adaptive Pipeline — DESIGN FLAW

**What works:**
- Discovery loop iterates correctly (iteration 0 → iteration 1)
- Company exclusion working (attempted companies excluded in next iteration)
- Result merging and deduplication logic correct

**What's broken:**
- **Timeout in any discovery step kills the entire iteration** (critical flaw)
  - When `_run_agent_step` returns `RunResult` (on timeout/fatal error), the adaptive pipeline restores `prev_scored` and exits the loop
  - Any partial results from the timed-out step are lost
  - In iteration 1: LinkedIn (20 JSON jobs) and Stripe (20 JSON jobs) were fetched but never processed because the scraper step timed out
- **Per-iteration state reset discards raw_jobs from previous steps**
  - Lines 132-134: `state.companies = []`, `state.raw_jobs = []`, `state.normalized_jobs = []`
  - This is correct for between-iteration cleanup, but if the scraper partially completed, those raw_jobs are lost

**Fix Plan:**
- **Fix A**: Change `_run_agent_step` timeout handling to NOT return `RunResult` for scraper step — instead, catch `TimeoutError` in `_discovery_loop`, log it, and continue with whatever results were accumulated in state before the timeout
- **Fix B**: Add partial-result preservation: when scraper times out, the already-completed company results should still be in `state.raw_jobs`. The adaptive pipeline should process what it has rather than discarding everything.

---

## Priority-Ordered Fix Plan

### Phase 1 (Critical — enables any results at all)

**Fix 1: Reorder scraper to probe ATS boards FIRST** (30 min)
- In `_scrape_via_crawler()`, call `_probe_ats_boards()` immediately, before crawling
- If ATS probe succeeds → return JSON jobs (fast, reliable, no browser needed)
- If probe fails → proceed with normal crawl + search flow
- This means LinkedIn and Stripe return results in ~5s, well before the 300s timeout

**Fix 2: Handle scraper timeout gracefully** (20 min)
- In `AdaptivePipeline._discovery_loop()`, don't abort on `RunResult` from scraper timeout
- Instead, check if `state.raw_jobs` has any content. If yes, continue to processor and scorer.
- This preserves partial results from companies that completed before the timeout.

### Phase 2 (High — improves results quality)

**Fix 3: Increase scraper timeout to 600s** (5 min)
- Change `agent_timeout_seconds` default from 300 to 600
- Or make it configurable per-step (scraper needs more time than other agents)

**Fix 4: Add per-company timeout in scraper** (20 min)
- Each company gets a 45s timeout via `asyncio.wait_for()` around `_do_scrape()`
- Companies that timeout are skipped but don't kill the entire step
- Already-completed companies' results are preserved

**Fix 5: Lower min_score_threshold temporarily** (2 min)
- Change from 80 to 60 in `run_live_pipeline.py` to get some initial results while debugging

### Phase 3 (Medium — reduces waste)

**Fix 6: Skip LLM processing for obviously non-job content** (15 min)
- Before calling LLM in `_process_from_html()`, check if the HTML contains job-related keywords
- If content has no mentions of "apply", "job", "engineer", "position", "developer", etc. → skip
- Saves ~$0.12 per non-job landing page

**Fix 7: Rate-limit DuckDuckGo search queries** (10 min)
- Add 1-second delay between search queries to avoid getting rate-limited
- Or better: skip search entirely if ATS probing already found results for the company

---

## Expected Improvement After Fixes

| Metric | Current | After Phase 1 | After Phase 2 |
|--------|---------|---------------|---------------|
| Companies with jobs | 1/16 | 3-5/16 | 5-8/16 |
| Raw jobs | 8 | 40-60 | 60-100 |
| Normalized jobs | 1 | 30-50 | 50-80 |
| Scored jobs | 0 | 10-30 | 20-50 |
| Cost | $0.84 | ~$0.50 | ~$0.70 |
| Duration | 718s | ~200s | ~300s |

The key insight: **ATS board probing is the path to success**. LinkedIn (Greenhouse), Stripe (Greenhouse), and likely many other companies have discoverable ATS boards. By probing first and only crawling as fallback, we skip the slow, unreliable crawl4ai + DuckDuckGo path for most companies.
