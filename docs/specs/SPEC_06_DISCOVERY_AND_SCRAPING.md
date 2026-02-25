# SPEC_06: Discovery and Scraping

## Purpose

The discovery and scraping agents are pipeline steps 3 and 4. `CompanyFinderAgent` takes the candidate's profile and preferences, generates a list of target companies via LLM reasoning, validates their career page URLs via web search, and detects which Applicant Tracking System (ATS) each company uses. `JobsScraperAgent` then takes those companies and scrapes raw job listings concurrently, routing each company to either an ATS-specific API client or a generic web crawler based on the detected scrape strategy.

## Key Files

| File | Primary Exports | Lines |
|------|----------------|-------|
| `src/job_hunter_agents/agents/company_finder.py` | `CompanyCandidate`, `CompanyCandidateList`, `CompanyFinderAgent` | 171 |
| `src/job_hunter_agents/agents/jobs_scraper.py` | `JobsScraperAgent` | 117 |
| `src/job_hunter_agents/prompts/company_finder.py` | `COMPANY_FINDER_SYSTEM`, `COMPANY_FINDER_USER` | 48 |
| `src/job_hunter_agents/tools/web_search.py` | `WebSearchTool`, `SearchResult` | 73 |
| `src/job_hunter_agents/tools/browser.py` | `WebScraper` | 61 |
| `src/job_hunter_agents/tools/ats_clients/base.py` | `BaseATSClient` (ABC) | 22 |
| `src/job_hunter_agents/tools/ats_clients/greenhouse.py` | `GreenhouseClient` | 51 |
| `src/job_hunter_agents/tools/ats_clients/lever.py` | `LeverClient` | 50 |
| `src/job_hunter_agents/tools/ats_clients/ashby.py` | `AshbyClient` | 51 |
| `src/job_hunter_agents/tools/ats_clients/workday.py` | `WorkdayClient` | 43 |
| `tests/unit/agents/test_company_finder.py` | `TestCompanyFinderAgent` (4 tests) | 139 |
| `tests/unit/agents/test_jobs_scraper.py` | `TestJobsScraperAgent` (3 tests) | 126 |

## Public API

### CompanyFinderAgent

```python
class CompanyCandidate(BaseModel):
    """LLM-generated company candidate."""
    name: str          # Company name
    domain: str        # Company website domain
    industry: str | None = None
    size: str | None = None
    description: str | None = None

class CompanyCandidateList(BaseModel):
    """List of company candidates from LLM."""
    companies: list[CompanyCandidate]

class CompanyFinderAgent(BaseAgent):
    agent_name = "company_finder"

    async def run(self, state: PipelineState) -> PipelineState
```

**Step-by-step logic of `run()`:**

1. **Log start** -- calls `self._log_start()` (no extra context).
2. **Precondition check** -- asserts that both `state.profile` and `state.preferences` are not `None`. If either is missing, raises `FatalAgentError("Profile and preferences must be parsed before finding companies")`. This is a hard stop.
3. **Generate candidates** -- calls `self._generate_candidates(state)` to get a `list[CompanyCandidate]`. See details below.
4. **Validate and build companies** -- iterates over each `CompanyCandidate` and calls `self._validate_and_build(candidate)`. Each call:
   - Searches for the company's career page URL.
   - Detects the ATS type.
   - Returns a `Company` model or `None` if no career page found.
   - On any exception, the error is recorded via `self._record_error(state, e, company_name=candidate.name)` and processing continues to the next candidate (per-company error isolation).
5. **Fatal check on empty results** -- if no companies have valid career pages after validation, raises `FatalAgentError("No companies found with valid career pages")`.
6. **Apply company limit** -- if `state.config.company_limit` is set (an `int | None` from `RunConfig`), slices the list: `companies = companies[:state.config.company_limit]`.
7. **Write to state** -- `state.companies = companies`.
8. **Log end** -- calls `self._log_end()` with duration and `companies_found` count.
9. **Return state**.

**Outputs written to `state`:**
- `state.companies` (`list[Company]`) -- validated companies with career page URLs and ATS types.

---

**`_generate_candidates(state)` -- internal method:**

```python
async def _generate_candidates(self, state: PipelineState) -> list[CompanyCandidate]
```

Two code paths:

**Path A: User specified preferred companies.** If `prefs.preferred_companies` is non-empty, creates `CompanyCandidate` objects directly from those names with synthetic domains (`name.lower().replace(' ', '') + ".com"`). No LLM call is made.

**Path B: LLM generation.** Calls `self._call_llm()` with:
- `messages`: a single user message using `COMPANY_FINDER_USER` template with 14 placeholder variables filled from `state.profile` and `state.preferences` (see Prompt Templates section below).
- `model`: `self.settings.sonnet_model` (default: `"claude-sonnet-4-5-20250514"`). This uses the higher-quality Sonnet model because company selection requires nuanced reasoning.
- `response_model`: `CompanyCandidateList` -- the LLM returns a list of 20-30 companies.
- `state`: passed for cost tracking.
- Returns `result.companies`.

---

**`_validate_and_build(candidate)` -- internal method:**

```python
async def _validate_and_build(self, candidate: CompanyCandidate) -> Company | None
```

1. **Find career URL** -- calls `self._find_career_url(candidate)` which delegates to `WebSearchTool.find_career_page(candidate.name)`. Uses the Tavily API to search for `"{company_name} careers jobs official site"`, then picks the first result URL containing "career", "jobs", "hiring", or "work" keywords. Falls back to the first result URL if no keyword match. Returns `None` if no results.
2. **Career page not found** -- if `career_url` is `None`, logs a warning and returns `None`. The company is silently dropped.
3. **Detect ATS** -- calls `self._detect_ats(career_url)` which returns a `tuple[ATSType, str]` (ATS type and scrape strategy).
4. **Build Company model** -- constructs and returns a `Company` with the candidate's metadata and a `CareerPage` sub-model containing the URL, ATS type, and scrape strategy.

---

**`_find_career_url(candidate)` -- internal method:**

```python
async def _find_career_url(self, candidate: CompanyCandidate) -> str | None
```

Instantiates `WebSearchTool(api_key=self.settings.tavily_api_key.get_secret_value())` and calls `search_tool.find_career_page(candidate.name)`. The `WebSearchTool` is a thin wrapper around the Tavily search API.

---

**`_detect_ats(career_url)` -- internal method:**

```python
async def _detect_ats(self, career_url: str) -> tuple[ATSType, str]
```

Iterates through a list of ATS client/type pairs in order:
1. `GreenhouseClient()` -- matches `boards.greenhouse.io/{slug}`
2. `LeverClient()` -- matches `jobs.lever.co/{slug}`
3. `AshbyClient()` -- matches `jobs.ashbyhq.com/{slug}`
4. `WorkdayClient()` -- matches `myworkdayjobs.com` or `workday.com/en-US`

For each, calls `await client.detect(career_url)` which performs a regex match against the URL. If a match is found, returns `(ats_type, "api")`. If none match, returns `(ATSType.UNKNOWN, "crawl4ai")`.

The detection is URL-pattern-based only -- no HTTP requests are made during detection.

---

### JobsScraperAgent

```python
class JobsScraperAgent(BaseAgent):
    agent_name = "jobs_scraper"

    async def run(self, state: PipelineState) -> PipelineState
```

**Step-by-step logic of `run()`:**

1. **Log start** -- calls `self._log_start({"companies_count": len(state.companies)})`.
2. **Create concurrency limiter** -- `semaphore = asyncio.Semaphore(self.settings.max_concurrent_scrapers)`. Default is 5 concurrent scrapers.
3. **Launch concurrent scrapes** -- creates a list of `_scrape_company(company, semaphore, state)` coroutines for every company in `state.companies`, then runs them with `asyncio.gather(*tasks, return_exceptions=True)`.
4. **Collect results** -- iterates over `results`. If a result is a `list[RawJob]`, extends `state.raw_jobs`. If it is an `Exception`, records it via `self._record_error(state, result)`.
5. **Log end** -- calls `self._log_end()` with duration and `raw_jobs_count`.
6. **Return state**.

**Outputs written to `state`:**
- `state.raw_jobs` (`list[RawJob]`) -- accumulated from all successful company scrapes.

---

**`_scrape_company(company, semaphore, state)` -- internal method:**

```python
async def _scrape_company(
    self,
    company: Company,
    semaphore: asyncio.Semaphore,
    state: PipelineState,
) -> list[RawJob]
```

Acquires the semaphore (`async with semaphore`), then calls `self._do_scrape(company)`. If `_do_scrape` raises any exception, the error is recorded via `self._record_error(state, e, company_name=company.name)` and an empty list is returned. The pipeline continues to scrape the remaining companies.

---

**`_do_scrape(company)` -- internal method:**

```python
async def _do_scrape(self, company: Company) -> list[RawJob]
```

Routes by `company.career_page.scrape_strategy`:
- `"api"` -- calls `self._scrape_via_api(company)`
- Any other value (including `"crawl4ai"`) -- calls `self._scrape_via_crawler(company, career_url)`

---

**`_scrape_via_api(company)` -- internal method:**

```python
async def _scrape_via_api(self, company: Company) -> list[RawJob]
```

1. Looks up the appropriate ATS client from a dict keyed by `ATSType`:
   - `ATSType.GREENHOUSE` -> `GreenhouseClient()`
   - `ATSType.LEVER` -> `LeverClient()`
   - `ATSType.ASHBY` -> `AshbyClient()`
   - `ATSType.WORKDAY` -> `WorkdayClient()`
2. If no client matches the `ats_type`, falls back to `_scrape_via_crawler`.
3. Calls `await client.fetch_jobs(company)` which returns `list[dict]`.
4. Wraps each dict into a `RawJob` with:
   - `company_id=company.id`
   - `company_name=company.name`
   - `raw_json=job_dict`
   - `source_url=company.career_page.url`
   - `scrape_strategy="api"`
   - `source_confidence=0.95`

---

**`_scrape_via_crawler(company, career_url)` -- internal method:**

```python
async def _scrape_via_crawler(self, company: Company, career_url: str) -> list[RawJob]
```

1. Instantiates `WebScraper()`.
2. Calls `await scraper.fetch_page(career_url)` which:
   - Primary: uses `crawl4ai.AsyncWebCrawler` to fetch and render the page (handles JS, SPAs, infinite scroll). Returns markdown or HTML.
   - Fallback: if crawl4ai fails, uses raw Playwright (`chromium.launch(headless=True)` with `networkidle` wait and 30s timeout).
3. Returns a single `RawJob` with:
   - `company_id=company.id`
   - `company_name=company.name`
   - `raw_html=content`
   - `source_url=company.career_page.url`
   - `scrape_strategy="crawl4ai"`
   - `source_confidence=0.7` (lower than API because HTML parsing is less reliable)

Note: The crawler strategy returns a single `RawJob` containing the entire page content. Downstream processing (the normalizer agent) is responsible for extracting individual job listings from this raw HTML/markdown.

## Prompt Templates

### Company Finder Prompts (`prompts/company_finder.py`)

**`COMPANY_FINDER_SYSTEM`** (defined but not currently passed in the agent's `_call_llm` call):

```
You are a company research assistant. Given a candidate profile and their job
search preferences, generate a list of real companies that would be good targets.

<rules>
- Only suggest REAL companies that currently exist and are actively hiring
- Match company suggestions to the candidate's industry experience and preferences
- Consider company size, location, and org type preferences
- Include a mix of well-known and lesser-known companies
- Provide the company's primary domain (e.g., stripe.com, not www.stripe.com)
- Do NOT suggest companies the candidate listed in excluded_companies
- If preferred_companies are specified, prioritize those
</rules>
```

**`COMPANY_FINDER_USER`** -- template variables (14 total):

| Variable | Source | Fallback if empty |
|----------|--------|------------------|
| `{name}` | `profile.name` | n/a (required) |
| `{current_title}` | `profile.current_title` | `"Not specified"` |
| `{years_of_experience}` | `profile.years_of_experience` | n/a (required, numeric) |
| `{skills}` | `", ".join(s.name for s in profile.skills)` | empty string |
| `{industries}` | `", ".join(profile.industries)` | `"Not specified"` |
| `{tech_stack}` | `", ".join(profile.tech_stack)` | `"Not specified"` |
| `{target_titles}` | `", ".join(prefs.target_titles)` | `"Any"` |
| `{target_seniority}` | `", ".join(prefs.target_seniority)` | `"Any"` |
| `{preferred_locations}` | `", ".join(prefs.preferred_locations)` | `"Any"` |
| `{remote_preference}` | `prefs.remote_preference` | n/a (defaults to `"any"`) |
| `{preferred_industries}` | `", ".join(prefs.preferred_industries)` | `"Any"` |
| `{org_types}` | `", ".join(prefs.org_types)` | n/a (defaults to `["any"]`) |
| `{company_sizes}` | `", ".join(prefs.company_sizes)` | `"Any"` |
| `{excluded_companies}` | `", ".join(prefs.excluded_companies)` | `"None"` |
| `{preferred_companies}` | `", ".join(prefs.preferred_companies)` | `"None"` |

Full template:

```
<candidate_profile>
Name: {name}
Current Title: {current_title}
Years of Experience: {years_of_experience}
Skills: {skills}
Industries: {industries}
Tech Stack: {tech_stack}
</candidate_profile>

<search_preferences>
Target Titles: {target_titles}
Target Seniority: {target_seniority}
Preferred Locations: {preferred_locations}
Remote Preference: {remote_preference}
Preferred Industries: {preferred_industries}
Organization Types: {org_types}
Company Sizes: {company_sizes}
Excluded Companies: {excluded_companies}
Preferred Companies: {preferred_companies}
</search_preferences>

Generate 20-30 target companies. For each, provide:
- name: Company name
- domain: Primary website domain
- industry: Company's primary industry
- size: Company size category (startup/mid/large/enterprise)
- description: Brief one-line description
```

The LLM is instructed to return 20-30 companies. The response is validated against `CompanyCandidateList` (a list of `CompanyCandidate` Pydantic models) by `instructor`.

**Note:** As with the parsing agents, the system prompt is defined but not included in the `messages` list. Only the user message is sent.

## Internal Dependencies

| Dependency | Source | Used By | Purpose |
|-----------|--------|---------|---------|
| `BaseAgent` | `job_hunter_agents.agents.base` | Both agents | LLM calling, cost tracking, error recording, logging |
| `CandidateProfile` | `job_hunter_core.models.candidate` | `CompanyFinderAgent` | Read from `state.profile` for prompt formatting |
| `SearchPreferences` | `job_hunter_core.models.candidate` | `CompanyFinderAgent` | Read from `state.preferences` for prompt formatting |
| `Company`, `CareerPage`, `ATSType` | `job_hunter_core.models.company` | Both agents | Company model construction and ATS routing |
| `RawJob` | `job_hunter_core.models.job` | `JobsScraperAgent` | Output model for scraped job data |
| `PipelineState` | `job_hunter_core.state` | Both agents | Input/output state container |
| `FatalAgentError` | `job_hunter_core.exceptions` | `CompanyFinderAgent` | Raised on missing preconditions or zero valid companies |
| `COMPANY_FINDER_USER` | `job_hunter_agents.prompts.company_finder` | `CompanyFinderAgent` | Prompt template |
| `WebSearchTool` | `job_hunter_agents.tools.web_search` | `CompanyFinderAgent` | Tavily-powered career page URL discovery |
| `WebScraper` | `job_hunter_agents.tools.browser` | `JobsScraperAgent` | crawl4ai + Playwright page fetching |
| `GreenhouseClient` | `job_hunter_agents.tools.ats_clients.greenhouse` | Both agents | Greenhouse ATS detection and API scraping |
| `LeverClient` | `job_hunter_agents.tools.ats_clients.lever` | Both agents | Lever ATS detection and API scraping |
| `AshbyClient` | `job_hunter_agents.tools.ats_clients.ashby` | Both agents | Ashby ATS detection and API scraping |
| `WorkdayClient` | `job_hunter_agents.tools.ats_clients.workday` | Both agents | Workday ATS detection and crawl-based scraping |
| `BaseATSClient` | `job_hunter_agents.tools.ats_clients.base` | ATS clients | Abstract base class defining `detect()` and `fetch_jobs()` interface |
| `Settings` | `job_hunter_core.config.settings` | Both (via `BaseAgent.__init__`) | Model selection, API keys, concurrency settings |

## External Dependencies

| Package | Used By | Purpose |
|---------|---------|---------|
| `anthropic` | `BaseAgent` (inherited) | Async Anthropic SDK for Claude API |
| `instructor` | `BaseAgent` (inherited) | Structured LLM output via Pydantic validation |
| `tenacity` | `BaseAgent` (inherited) | Retry with exponential backoff |
| `structlog` | All agents and tools | Structured logging |
| `tavily` | `WebSearchTool` | Web search API for career page discovery |
| `httpx` | `GreenhouseClient`, `LeverClient`, `AshbyClient`, `WebScraper` | Async HTTP client for ATS APIs and JSON endpoints |
| `crawl4ai` | `WebScraper` | Primary web scraping with JS rendering |
| `playwright` | `WebScraper` (fallback), `WorkdayClient` (indirect) | Headless Chromium for pages crawl4ai cannot handle |
| `pydantic` | `CompanyCandidate`, `CompanyCandidateList`, domain models | Model validation |
| `asyncio` | `JobsScraperAgent` | `Semaphore` for concurrency control, `gather` for parallel execution |

## Data Flow

### Company Discovery

```
state.profile (CandidateProfile) + state.preferences (SearchPreferences)
    |
    |--- [preferred_companies is non-empty?]
    |       YES --> CompanyCandidate objects from preferred names (synthetic domains)
    |       NO  --> COMPANY_FINDER_USER.format(14 variables)
    |                   |
    |                   v
    |               _call_llm(model=sonnet, response_model=CompanyCandidateList)
    |                   |
    |                   v
    |               list[CompanyCandidate]  (20-30 candidates)
    |
    v
For each CompanyCandidate:
    |
    v
_find_career_url(candidate)
    |  WebSearchTool.find_career_page(candidate.name)
    |  Tavily search: "{name} careers jobs official site"
    |  Returns: career URL string or None
    |
    |--- [career_url is None?]
    |       YES --> log warning, skip company (return None)
    |       NO  --> continue
    |
    v
_detect_ats(career_url)
    |  Regex pattern matching against URL:
    |    boards.greenhouse.io/{slug}  --> (GREENHOUSE, "api")
    |    jobs.lever.co/{slug}         --> (LEVER, "api")
    |    jobs.ashbyhq.com/{slug}      --> (ASHBY, "api")
    |    myworkdayjobs.com|workday    --> (WORKDAY, "api")
    |    no match                     --> (UNKNOWN, "crawl4ai")
    |
    v
Company(name, domain, CareerPage(url, ats_type, scrape_strategy), industry, size, description)
    |
    v
[Exception during validation? --> _record_error(), skip company]
    |
    v
[No companies valid? --> FatalAgentError]
    |
    v
[Apply company_limit if set: companies[:limit]]
    |
    v
state.companies = list[Company]
```

### Job Scraping

```
state.companies (list[Company])
    |
    v
asyncio.Semaphore(max_concurrent_scrapers)  [default: 5]
    |
    v
asyncio.gather(*[_scrape_company(c, sem, state) for c in companies],
               return_exceptions=True)
    |
    |--- For each company (concurrently, limited by semaphore):
    |
    v
_do_scrape(company)
    |
    |--- [scrape_strategy == "api"?]
    |       |
    |       v
    |   _scrape_via_api(company)
    |       |  Lookup ATS client by ats_type:
    |       |    GREENHOUSE -> GreenhouseClient.fetch_jobs(company)
    |       |      API: boards-api.greenhouse.io/v1/boards/{slug}/jobs
    |       |    LEVER -> LeverClient.fetch_jobs(company)
    |       |      API: api.lever.co/v0/postings/{slug}
    |       |    ASHBY -> AshbyClient.fetch_jobs(company)
    |       |      API: api.ashbyhq.com/posting-api/job-board/{slug}
    |       |    WORKDAY -> WorkdayClient.fetch_jobs(company)
    |       |      Crawl: scraper.fetch_page(url) -> {"raw_content": html}
    |       |    None -> fallback to _scrape_via_crawler
    |       |
    |       v
    |   list[RawJob] with raw_json=job_dict, source_confidence=0.95
    |
    |--- [scrape_strategy != "api" (i.e. "crawl4ai")]
    |       |
    |       v
    |   _scrape_via_crawler(company, career_url)
    |       |  WebScraper.fetch_page(career_url)
    |       |    Primary: crawl4ai AsyncWebCrawler
    |       |    Fallback: Playwright headless Chromium (30s timeout)
    |       |
    |       v
    |   [RawJob] with raw_html=content, source_confidence=0.7
    |
    v
[Exception? --> _record_error(state, e, company_name), return []]
    |
    v
Results aggregated: state.raw_jobs.extend(successful_results)
```

### Pipeline Position

```
Pipeline step order:
  1. ResumeParserAgent.run()
  2. PrefsParserAgent.run()
  3. CompanyFinderAgent.run()   <-- reads state.profile + state.preferences,
                                    writes state.companies
  4. JobsScraperAgent.run()    <-- reads state.companies,
                                    writes state.raw_jobs
  5. JobsProcessorAgent.run()   (reads state.raw_jobs)
  6. ...
```

## Configuration

| Setting | Default | Used By | Purpose |
|---------|---------|---------|---------|
| `sonnet_model` | `"claude-sonnet-4-5-20250514"` | `CompanyFinderAgent` | LLM model for company generation (higher quality) |
| `tavily_api_key` | required (`SecretStr`) | `CompanyFinderAgent` via `WebSearchTool` | Tavily API authentication for career page search |
| `max_concurrent_scrapers` | `5` | `JobsScraperAgent` | Semaphore limit for concurrent scrape tasks |
| `scrape_timeout_seconds` | `30` | `WebScraper` (Playwright fallback) | Timeout per page fetch. Note: currently hardcoded in `WebScraper.fetch_page_playwright()` as `timeout=30000` and in `WebScraper.fetch_json_api()` as `timeout=30.0`. Not dynamically read from settings by the scraper agent. |
| `scraper_retry_max` | `3` | Not currently wired | Defined in settings but not used by `JobsScraperAgent` or `WebScraper`. Retry happens only at the LLM level (via `_call_llm`), not at the scrape level. |
| `scraper_retry_wait_min` | `1.0` | Not currently wired | Same -- defined but unused. |
| `scraper_retry_wait_max` | `10.0` | Not currently wired | Same -- defined but unused. |
| `anthropic_api_key` | required (`SecretStr`) | Both (via `BaseAgent`) | Anthropic API authentication |
| `max_cost_per_run_usd` | `5.0` | `CompanyFinderAgent` (via `_track_cost`) | Cost guardrail |
| `warn_cost_threshold_usd` | `2.0` | `CompanyFinderAgent` (via `_track_cost`) | Cost warning threshold |
| `company_limit` | `None` (`int | None`, on `RunConfig`) | `CompanyFinderAgent` | Caps the number of companies to process (useful for testing/cost control) |

**Note on unwired settings:** `scrape_timeout_seconds`, `scraper_retry_max`, `scraper_retry_wait_min`, and `scraper_retry_wait_max` are defined in `Settings` but are not currently read by `JobsScraperAgent` or the tools it uses. The timeouts are hardcoded in the tool implementations. This is a known gap.

## Error Handling

### CompanyFinderAgent

| Error | Source | Behavior |
|-------|--------|----------|
| `FatalAgentError` | `run()` precondition check | Raised if `state.profile` or `state.preferences` is `None`. Stops the pipeline. |
| `FatalAgentError` | `run()` empty results check | Raised if no companies have valid career pages after all validation attempts. Stops the pipeline. |
| `anthropic.APIError` | `_call_llm()` | Retried up to 3 times with exponential backoff. If all fail, propagates. |
| `pydantic.ValidationError` | `instructor` validation | LLM output did not match `CompanyCandidateList` schema. Retried by instructor. |
| `CostLimitExceededError` | `_track_cost()` | Propagates -- fatal. |
| Any exception in `_validate_and_build()` | Tavily API errors, network failures | Caught per-company. Recorded via `_record_error(state, e, company_name=candidate.name)`. Processing continues to the next candidate. |

**Per-company error isolation:** The `_validate_and_build` call for each company is wrapped in a `try/except Exception` block. If validation fails for company X (e.g., Tavily returns an error, or the career page URL is unreachable), the error is logged and the agent moves on to company Y. Only if ALL companies fail does the `FatalAgentError` for empty results trigger.

### JobsScraperAgent

| Error | Source | Behavior |
|-------|--------|----------|
| Any exception in `_scrape_company()` | ATS API errors, crawl4ai/Playwright failures, network timeouts | Caught per-company inside `_scrape_company`. Recorded via `_record_error(state, e, company_name=company.name)`. Returns empty list. Other companies continue. |
| Exceptions returned by `asyncio.gather()` | Uncaught exceptions that bypass `_scrape_company`'s try/except | Detected in the results loop (`isinstance(result, Exception)`). Recorded via `_record_error(state, result)`. |
| `httpx.HTTPStatusError` | ATS API clients (`fetch_jobs`) | Raised when ATS API returns non-2xx status. Caught by `_scrape_company`'s exception handler. |

**Graceful degradation:** The scraper agent never raises a fatal error. Even if all companies fail to scrape, it returns the state with `raw_jobs = []` and errors recorded. The pipeline orchestrator decides whether to continue.

### ATS Client Error Handling

| Client | Detection Failure | Fetch Failure |
|--------|------------------|---------------|
| `GreenhouseClient` | Returns `False` from `detect()` (no regex match) | Returns `[]` if slug extraction fails. Raises `httpx.HTTPStatusError` on API errors. |
| `LeverClient` | Returns `False` from `detect()` | Returns `[]` if slug extraction fails. Raises `httpx.HTTPStatusError` on API errors. |
| `AshbyClient` | Returns `False` from `detect()` | Returns `[]` if slug extraction fails. Raises `httpx.HTTPStatusError` on API errors. |
| `WorkdayClient` | Returns `False` from `detect()` | Logs error and returns `[]` on any exception (internal try/except). |

### WebScraper Fallback Chain

```
fetch_page(url)
    |
    v
_fetch_crawl4ai(url)  [crawl4ai.AsyncWebCrawler]
    |
    |--- Success: return markdown or HTML content
    |--- Failure: log warning, fall through
    |
    v
fetch_page_playwright(url)  [Playwright headless Chromium]
    |
    |--- Success: return page HTML content
    |--- Failure: exception propagates to caller
```

## Testing

### Existing Tests

**`tests/unit/agents/test_company_finder.py`** -- `TestCompanyFinderAgent` (4 tests):

| Test | What It Verifies |
|------|-----------------|
| `test_raises_without_profile` | Raises `FatalAgentError` when `state.profile` is `None`. Mocks: `AsyncAnthropic`, `instructor`. |
| `test_uses_preferred_companies` | When `prefs.preferred_companies = ["Stripe", "Figma"]`, skips LLM call and uses preferred companies directly. Mocks: `_validate_and_build` (returns a valid `Company`), `AsyncAnthropic`, `instructor`. Asserts `len(result.companies) > 0`. |
| `test_ats_detection` | `_detect_ats("https://boards.greenhouse.io/stripe")` returns `(ATSType.GREENHOUSE, "api")`. Tests the regex pattern matching directly. |
| `test_ats_detection_unknown` | `_detect_ats("https://company.com/careers")` returns `(ATSType.UNKNOWN, "crawl4ai")`. |

**`tests/unit/agents/test_jobs_scraper.py`** -- `TestJobsScraperAgent` (3 tests):

| Test | What It Verifies |
|------|-----------------|
| `test_scrapes_via_crawler` | Single company with `crawl4ai` strategy. Mocks `WebScraper.fetch_page` to return `"<html>jobs</html>"`. Asserts one `RawJob` with `raw_html` set. |
| `test_handles_scrape_error` | `WebScraper.fetch_page` raises `RuntimeError`. Asserts `raw_jobs` is empty and `errors` has at least one entry. |
| `test_multiple_companies` | Two companies scraped concurrently. Both succeed. Asserts two `RawJob` entries. |

### Test Patterns

- `_make_settings()` provides mock settings with `anthropic_api_key`, `sonnet_model` / `tavily_api_key` (company finder) or `max_concurrent_scrapers` (scraper), and cost guardrails.
- `_make_company()` factory creates a `Company` with configurable `ats_type` and `scrape_strategy`.
- `AsyncAnthropic` and `instructor` are always patched in `job_hunter_agents.agents.base`.
- `WebScraper` is patched at the module level in `job_hunter_agents.agents.jobs_scraper`.

### Gaps / Potential Additions

- No test for LLM-generated candidates path (when `preferred_companies` is empty).
- No test for `_find_career_url` (Tavily search integration).
- No test for `company_limit` truncation.
- No test for `FatalAgentError` when all companies fail validation.
- No test for the `"api"` scrape strategy path (`_scrape_via_api`).
- No test for the `_scrape_via_api` fallback to crawler when `ats_type` is not in the clients dict.
- No test for `source_confidence` values (0.95 for API, 0.7 for crawler).
- No test verifying that `asyncio.Semaphore` actually limits concurrency.
- No integration test with real ATS APIs or Tavily.

## Common Modification Patterns

### Add a new company discovery source

To add an additional source of company candidates beyond LLM generation (e.g., a database of known companies, a third-party API):

1. Add a new private method to `CompanyFinderAgent`, e.g., `async def _fetch_from_database(self, state: PipelineState) -> list[CompanyCandidate]`.
2. Call it in `_generate_candidates()` alongside or instead of the LLM call. Consider merging/deduplicating results.
3. If the source requires new configuration (API key, URL), add it to `Settings` in `src/job_hunter_core/config/settings.py`.
4. Add the new setting to `.env.example`.
5. Write tests mocking the new source.

### Add a new ATS client

1. Create a new file `src/job_hunter_agents/tools/ats_clients/{name}.py`.
2. Implement a class extending `BaseATSClient` with `detect(career_url)` and `fetch_jobs(company)`.
3. Add the new ATS type to `ATSType` enum in `src/job_hunter_core/models/company.py` (e.g., `BAMBOOHR = "bamboohr"`).
4. Register the client in `CompanyFinderAgent._detect_ats()` -- add a `(NewClient(), ATSType.NEW)` tuple to the `clients` list.
5. Register the client in `JobsScraperAgent._scrape_via_api()` -- add `ATSType.NEW: NewClient()` to the `clients` dict.
6. Write unit tests for detection regex and `fetch_jobs`.
7. See CONTRIBUTING.md "ATS Support Request" issue template for the checklist.

### Modify scraping concurrency

1. The concurrency limit is controlled by `Settings.max_concurrent_scrapers` (default: `5`).
2. To change the default, edit the `Field(default=5)` in `src/job_hunter_core/config/settings.py`.
3. To override at runtime, set the `JH_MAX_CONCURRENT_SCRAPERS` environment variable.
4. The setting flows through `self.settings.max_concurrent_scrapers` into `asyncio.Semaphore()` in `JobsScraperAgent.run()`.

### Wire scraper retry/timeout settings

Currently `scrape_timeout_seconds`, `scraper_retry_max`, `scraper_retry_wait_min`, and `scraper_retry_wait_max` are defined in `Settings` but not used by the scraper agent or its tools. To wire them:

1. Pass `self.settings` (or specific values) to `WebScraper.__init__()`.
2. In `WebScraper.fetch_page_playwright()`, replace the hardcoded `timeout=30000` with `timeout=self.timeout_ms`.
3. In `WebScraper.fetch_json_api()`, replace `timeout=30.0` with `timeout=self.timeout_seconds`.
4. Wrap `_do_scrape` or `_scrape_company` with `tenacity.retry` using the retry settings.
5. Alternatively, wrap in `asyncio.wait_for(self._do_scrape(company), timeout=self.settings.scrape_timeout_seconds)`.

## Cross-References

- **SPEC_01** -- `Company`, `CareerPage`, `ATSType`, `RawJob`, `CandidateProfile`, `SearchPreferences`, `PipelineState`, `RunConfig`, `FatalAgentError` are all core models/exceptions.
- **SPEC_04** -- `BaseAgent` provides `_call_llm()`, `_track_cost()`, `_record_error()`, logging methods. The `Pipeline` orchestrator calls these agents at steps 3 and 4.
- **SPEC_05** -- Parsing agents are the upstream dependency: `CompanyFinderAgent` reads `state.profile` and `state.preferences` produced by `ResumeParserAgent` and `PrefsParserAgent`.
- **SPEC_07** -- `WebSearchTool` (Tavily), `WebScraper` (crawl4ai/Playwright), and `PDFParser` are tool implementations with their own specs.
- **SPEC_08** -- ATS clients (`GreenhouseClient`, `LeverClient`, `AshbyClient`, `WorkdayClient`) have detailed specs including URL patterns, API endpoints, and extraction logic.
- **SPEC_09** -- The downstream `JobsProcessorAgent` reads `state.raw_jobs` to normalize raw HTML/JSON into `NormalizedJob` models.
- **SPEC_10** -- Cost tracking: `CompanyFinderAgent`'s `_call_llm` call (Sonnet model) is the most expensive single LLM call in the pipeline.
- **SPEC_11** -- Test factories: `make_company()`, `make_raw_job()`, `make_candidate_profile()`, `make_search_preferences()` in `tests/mocks/mock_factories.py`.
