# GOAL: Usable Job Hunting Pipeline

## Definition of Done

The job-hunter-agent pipeline is **usable** when a single end-to-end run (adaptive pipeline with `local_claude`) produces:

1. **At least 10 scored jobs** above the `min_score_threshold` (60) in the final output CSV/XLSX
2. **Apply URLs** point to specific job postings (not generic career landing pages like `https://www.amazon.jobs/`)
3. **Posted Date** is populated for ATS-sourced jobs (Greenhouse/Lever/Ashby all provide dates)
4. **Company diversity** — all jobs must be from unique companies in the output
5. **Location relevance** — all of the scored jobs should match the candidate's location preference (India/Bangalore/Remote-global)
6. **Score calibration** — scores reflect genuine fit (strong matches 75+, decent matches 60-74, not inflated)
7. **Pipeline completes** without timeout or fatal errors within a single run (all 3 iterations if needed), output meeting all of the above critera for good quality predictions
8. **Total cost** under $5.00 per run

## Current State (2026-02-27, run_20260227_141103) — ALL GOALS MET

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Scored jobs above threshold | >= 10 | 11 | **PASS** |
| Apply URLs to specific jobs | 100% | 11/11 (100%) | **PASS** |
| Posted dates populated | ATS jobs | 11/11 (100%) | **PASS** |
| Company diversity | All unique | 11 unique companies | **PASS** |
| Location relevance | 100% India/Remote | 11/11 (100%) | **PASS** |
| Score calibration | Honest scoring | 62-85 range, good distribution | **PASS** |
| Pipeline completion | No timeout | Completed in 1110s (~18.5 min) | **PASS** |
| Cost per run | < $5.00 | $2.87 | **PASS** |

### Companies in Output
Commvault (85), Zscaler (83), Postman (78), Turing (72), Druva (72),
Databricks (70), Tekion (65), PhonePe (62), Coinbase (62), CockroachDB (62),
GitLab (62)

## Fixes Applied (All)
1. LLM/agent timeout increased to 600s
2. ATS-first scraper reorder (API before HTML)
3. `?content=true` for Greenhouse full JDs (removed double-append)
4. Posted date extraction from ATS JSON (updated_at, createdAt, publishedAt)
5. Apply URL from ATS JSON (absolute_url, applyUrl, applicationUrl)
6. Adaptive discovery loop (find→scrape→process→score, repeat)
7. 46 curated ATS seed companies, 17 India-tagged
8. Hard location filter with Indian city alias expansion
9. Company deduplication in aggregator
10. Unique company counting in adaptive loop
11. Incremental job accumulation in scraper
12. Empty-location non-remote job exclusion
13. top_k_semantic 25→40, max_discovery_iterations 3→5
14. Seed ratio ~67%, company_limit=20

## Remaining Issues

### P0: Still 6 unique companies, need 10
- Pre-filter selects 20 jobs from 2460 (iteration 0), but many companies overlap
- Scoring threshold (60) may be too strict for local_claude
- Some companies (InMobi, Turing, Groww) have India jobs but not matching skill keywords
- **Fix options**: Lower score threshold to 55, expand keyword matching, increase per-company limit for more diverse scoring

### P1: 1 location mismatch in 6
- Need to investigate which company's job doesn't match India/Remote keywords
- Likely a remote job without "remote" in location field

## Verification Command

```bash
# Run pipeline and check output
uv run python run_live_pipeline.py

# Verify results meet goals
python scripts/verify_goal.py output/run_*_results.csv
```

## Non-Goals (for now)
- Semantic/embedding-based job matching (pre-filter uses keyword matching, which is sufficient)
- Multi-provider LLM support (local_claude from llm-gateway is the target)
- Email notification
- Web UI
