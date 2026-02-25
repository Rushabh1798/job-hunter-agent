# SPEC_08: ATS Clients

## Purpose

Applicant Tracking System (ATS) clients detect whether a career page URL belongs to a known ATS platform and fetch structured job listings from that platform's API. Each client implements a common `BaseATSClient` ABC with two methods: `detect()` and `fetch_jobs()`. Three of the four clients (Greenhouse, Lever, Ashby) use public JSON APIs. Workday has no public API and falls back to crawl4ai-based scraping.

ATS clients are a specialized subset of tools (SPEC_07). They live under `tools/ats_clients/` and follow the same conventions: stateless, async, no agent imports.

## Key Files

| File | Primary Exports | Lines |
|------|----------------|-------|
| `src/job_hunter_agents/tools/ats_clients/__init__.py` | (empty -- clients imported directly) | 1 |
| `src/job_hunter_agents/tools/ats_clients/base.py` | `BaseATSClient` (ABC) | 22 |
| `src/job_hunter_agents/tools/ats_clients/greenhouse.py` | `GreenhouseClient`, `GREENHOUSE_BOARD_PATTERN`, `GREENHOUSE_API_URL` | 51 |
| `src/job_hunter_agents/tools/ats_clients/lever.py` | `LeverClient`, `LEVER_PATTERN`, `LEVER_API_URL` | 50 |
| `src/job_hunter_agents/tools/ats_clients/ashby.py` | `AshbyClient`, `ASHBY_PATTERN`, `ASHBY_API_URL` | 51 |
| `src/job_hunter_agents/tools/ats_clients/workday.py` | `WorkdayClient`, `WORKDAY_PATTERN` | 43 |

## Public API

### BaseATSClient (ABC) (`ats_clients/base.py`)

```python
class BaseATSClient(ABC):
    """Abstract base class for Applicant Tracking System clients."""

    @abstractmethod
    async def detect(self, career_url: str) -> bool:
        """Return True if this ATS type is detected at the given URL."""
        ...

    @abstractmethod
    async def fetch_jobs(self, company: Company) -> list[dict]:
        """Return raw job dicts from the ATS API.
        Reads career page URL from company.career_page.url."""
        ...
```

**Import:** `from job_hunter_core.models.company import Company`

All concrete clients inherit from `BaseATSClient` and implement both methods. The `detect()` method is a pure regex match (no network call). The `fetch_jobs()` method makes an HTTP request and returns raw JSON dicts.

---

### GreenhouseClient (`ats_clients/greenhouse.py`)

**URL regex pattern:**
```python
GREENHOUSE_BOARD_PATTERN = re.compile(r"boards\.greenhouse\.io/(\w+)", re.IGNORECASE)
```

**Matches:** `https://boards.greenhouse.io/stripe`, `https://boards.greenhouse.io/AcmeCorp/jobs/123`

**Does not match:** `https://stripe.com/careers`, `https://greenhouse.io/company`

**API endpoint template:**
```python
GREENHOUSE_API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
```

**Constructor:** No parameters.

**`detect(career_url: str) -> bool`:**
- Applies `GREENHOUSE_BOARD_PATTERN.search(career_url)`
- Returns `True` if match found, `False` otherwise
- No network call

**`_extract_slug(career_url: str) -> str | None`:**
- Extracts capture group 1 from `GREENHOUSE_BOARD_PATTERN`
- Example: `"https://boards.greenhouse.io/stripe"` -> `"stripe"`
- Returns `None` if no match

**`fetch_jobs(company: Company) -> list[dict]`:**
1. Reads URL from `str(company.career_page.url)`
2. Calls `_extract_slug()` -- returns `[]` with warning if slug is None
3. Constructs API URL: `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`
4. `httpx.AsyncClient(timeout=30.0).get(api_url)`
5. Calls `response.raise_for_status()`
6. Parses JSON and returns `data["jobs"]` (list of dicts)
7. Logs `greenhouse_jobs_fetched` with company name and count

**Response structure (from `tests/fixtures/ats_responses/greenhouse_jobs.json`):**
```json
{
  "jobs": [
    {
      "id": 100001,
      "title": "Senior Backend Engineer",
      "content": "We are looking for...",
      "absolute_url": "https://boards.greenhouse.io/acmecorp/jobs/100001",
      "location": { "name": "San Francisco, CA" },
      "updated_at": "2026-02-20T12:00:00Z",
      "departments": [ { "name": "Engineering" } ]
    }
  ]
}
```

**Key fields per job dict:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | `int` | Greenhouse job ID |
| `title` | `str` | Job title |
| `content` | `str` | Full job description (HTML-stripped) |
| `absolute_url` | `str` | Direct apply URL |
| `location.name` | `str` | Location string |
| `updated_at` | `str` (ISO 8601) | Last update timestamp |
| `departments` | `list[dict]` | Each with `"name"` key |

---

### LeverClient (`ats_clients/lever.py`)

**URL regex pattern:**
```python
LEVER_PATTERN = re.compile(r"jobs\.lever\.co/(\w[\w-]*)", re.IGNORECASE)
```

**Matches:** `https://jobs.lever.co/figma`, `https://jobs.lever.co/my-company/some-job-id`

**Does not match:** `https://lever.co/figma`, `https://figma.com/careers`

**API endpoint template:**
```python
LEVER_API_URL = "https://api.lever.co/v0/postings/{slug}"
```

**Constructor:** No parameters.

**`detect(career_url: str) -> bool`:**
- Applies `LEVER_PATTERN.search(career_url)`
- Returns `True` if match found, `False` otherwise

**`_extract_slug(career_url: str) -> str | None`:**
- Extracts capture group 1 from `LEVER_PATTERN`
- Example: `"https://jobs.lever.co/figma"` -> `"figma"`
- Supports slugs with hyphens: `"https://jobs.lever.co/my-company"` -> `"my-company"`
- Returns `None` if no match

**`fetch_jobs(company: Company) -> list[dict]`:**
1. Reads URL from `str(company.career_page.url)`
2. Calls `_extract_slug()` -- returns `[]` with warning if slug is None
3. Constructs API URL: `https://api.lever.co/v0/postings/{slug}`
4. `httpx.AsyncClient(timeout=30.0).get(api_url)`
5. Calls `response.raise_for_status()`
6. Parses JSON and returns the response directly (it is a list, not wrapped in an object)
7. Logs `lever_jobs_fetched` with company name and count

**Response structure (from `tests/fixtures/ats_responses/lever_jobs.json`):**
```json
[
  {
    "id": "lever-200001",
    "text": "Data Engineer",
    "description": "Join our data team...",
    "descriptionPlain": "Join our data team...",
    "categories": {
      "location": "San Francisco, CA",
      "team": "Data Engineering",
      "commitment": "Full-time"
    },
    "applyUrl": "https://jobs.lever.co/dataflow/200001/apply",
    "hostedUrl": "https://jobs.lever.co/dataflow/200001",
    "createdAt": 1708300800000
  }
]
```

**NOTE:** Lever API returns a **top-level JSON array** (not wrapped in `{"jobs": [...]}`). This differs from Greenhouse and Ashby.

**Key fields per job dict:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Lever posting ID |
| `text` | `str` | Job title (note: `text` not `title`) |
| `description` | `str` | HTML description |
| `descriptionPlain` | `str` | Plain text description |
| `categories.location` | `str` | Location string |
| `categories.team` | `str` | Team/department |
| `categories.commitment` | `str` | Full-time, Part-time, etc. |
| `applyUrl` | `str` | Direct apply URL |
| `hostedUrl` | `str` | Public posting URL |
| `createdAt` | `int` | Unix timestamp in milliseconds |

---

### AshbyClient (`ats_clients/ashby.py`)

**URL regex pattern:**
```python
ASHBY_PATTERN = re.compile(r"jobs\.ashbyhq\.com/(\w[\w-]*)", re.IGNORECASE)
```

**Matches:** `https://jobs.ashbyhq.com/notion`, `https://jobs.ashbyhq.com/cloud-nova/300001/apply`

**Does not match:** `https://ashbyhq.com/notion`, `https://notion.so/careers`

**API endpoint template:**
```python
ASHBY_API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
```

**Constructor:** No parameters.

**`detect(career_url: str) -> bool`:**
- Applies `ASHBY_PATTERN.search(career_url)`
- Returns `True` if match found, `False` otherwise

**`_extract_slug(career_url: str) -> str | None`:**
- Extracts capture group 1 from `ASHBY_PATTERN`
- Example: `"https://jobs.ashbyhq.com/notion"` -> `"notion"`
- Returns `None` if no match

**`fetch_jobs(company: Company) -> list[dict]`:**
1. Reads URL from `str(company.career_page.url)`
2. Calls `_extract_slug()` -- returns `[]` with warning if slug is None
3. Constructs API URL: `https://api.ashbyhq.com/posting-api/job-board/{slug}`
4. `httpx.AsyncClient(timeout=30.0).get(api_url)`
5. Calls `response.raise_for_status()`
6. Parses JSON and returns `data["jobs"]` (list of dicts)
7. Logs `ashby_jobs_fetched` with company name and count

**Response structure (from `tests/fixtures/ats_responses/ashby_jobs.json`):**
```json
{
  "jobs": [
    {
      "id": "ashby-300001",
      "title": "Full Stack Engineer",
      "description": "Build user-facing features...",
      "location": "Remote - US",
      "department": "Product Engineering",
      "publishedAt": "2026-02-15T08:00:00Z",
      "applicationUrl": "https://jobs.ashbyhq.com/cloudnova/300001/apply"
    }
  ]
}
```

**Key fields per job dict:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Ashby job ID |
| `title` | `str` | Job title |
| `description` | `str` | Job description |
| `location` | `str` | Location string |
| `department` | `str` | Department name |
| `publishedAt` | `str` (ISO 8601) | Publication timestamp |
| `applicationUrl` | `str` | Direct apply URL |

---

### WorkdayClient (`ats_clients/workday.py`)

**URL regex pattern:**
```python
WORKDAY_PATTERN = re.compile(r"myworkdayjobs\.com|workday\.com/en-US", re.IGNORECASE)
```

**Matches:** `https://company.myworkdayjobs.com/en-US`, `https://company.workday.com/en-US/recruiting`

**Does not match:** `https://company.com/careers`, `https://workday.com` (no `/en-US` path)

**No API endpoint template.** Workday does not expose a public jobs API. Uses crawl4ai-based scraping.

**Constructor:**
```python
def __init__(self) -> None:
    self._scraper = WebScraper()
```
Creates a `WebScraper` instance internally. This is the only ATS client with a dependency on another tool.

**`detect(career_url: str) -> bool`:**
- Applies `WORKDAY_PATTERN.search(career_url)`
- Returns `True` if match found, `False` otherwise

**`fetch_jobs(company: Company) -> list[dict]`:**
1. Reads URL from `str(company.career_page.url)`
2. Calls `self._scraper.fetch_page(url)` (crawl4ai with Playwright fallback)
3. On success: returns `[{"raw_content": content, "source_url": url}]` -- a single-element list with raw scraped content
4. On exception: logs error, returns `[]`
5. Logs `workday_page_fetched` with company name and content length

**NOTE:** Unlike the other three clients, Workday returns **raw page content** (not structured job listings). The downstream `JobsProcessorAgent` is responsible for parsing job listings from this content using LLM extraction.

**Special handling:**
- No `_extract_slug()` method (not needed -- no API to call)
- No `response.raise_for_status()` (scraper handles errors internally)
- Returns at most 1 dict per call (the entire page content)
- Catches all exceptions and returns `[]` on failure (graceful degradation)

## Internal Dependencies

- `job_hunter_core.models.company.Company` -- used as parameter type for `fetch_jobs()`
- `job_hunter_agents.tools.browser.WebScraper` -- used by `WorkdayClient` only

ATS clients do NOT import from agents, infra, or CLI packages.

## External Dependencies

| Client | Library | Purpose |
|--------|---------|---------|
| GreenhouseClient | `httpx` | HTTP GET to Greenhouse API |
| LeverClient | `httpx` | HTTP GET to Lever API |
| AshbyClient | `httpx` | HTTP GET to Ashby API |
| WorkdayClient | `crawl4ai` + `playwright` (via `WebScraper`) | Browser-based scraping |

All clients use `re` (stdlib) for URL pattern matching.

## Data Flow

```
career_url (from company.career_page.url)
  |
  v
detect(career_url)
  -> regex match against URL pattern
  -> True/False
  |
  v (if True)
fetch_jobs(company)
  |
  +-- [Greenhouse/Lever/Ashby]:
  |     -> _extract_slug(url) -> slug
  |     -> construct API URL from template + slug
  |     -> httpx.AsyncClient.get(api_url, timeout=30s)
  |     -> response.raise_for_status()
  |     -> response.json()
  |     -> extract "jobs" list (or use top-level list for Lever)
  |     -> list[dict]
  |
  +-- [Workday]:
        -> WebScraper.fetch_page(url)
        -> [{"raw_content": content, "source_url": url}]
```

### Response shape differences

| Client | Response root | Jobs accessor | Title field | Apply URL field |
|--------|--------------|---------------|-------------|-----------------|
| Greenhouse | `{"jobs": [...]}` | `data["jobs"]` | `"title"` | `"absolute_url"` |
| Lever | `[...]` (top-level array) | `data` (direct) | `"text"` | `"applyUrl"` |
| Ashby | `{"jobs": [...]}` | `data["jobs"]` | `"title"` | `"applicationUrl"` |
| Workday | N/A (raw scrape) | N/A | N/A | N/A |

## Configuration

ATS clients use no `Settings` fields directly. The `httpx.AsyncClient` timeout is hardcoded at 30 seconds in each client. The `WebScraper` used by `WorkdayClient` also has a 30-second timeout.

Agents that use ATS clients may pass `Settings.scrape_timeout_seconds` or `Settings.max_concurrent_scrapers` to control the calling context, but these are not read by the clients themselves.

## Error Handling

| Error | Source | Handling |
|-------|--------|----------|
| `httpx.HTTPStatusError` | `response.raise_for_status()` on Greenhouse/Lever/Ashby | Propagated to calling agent for retry or recording |
| `httpx.ConnectError` / `httpx.TimeoutException` | Network failures | Propagated to calling agent |
| Slug extraction failure (`None`) | `_extract_slug()` on non-matching URL | Logged as warning, returns `[]` (no error raised) |
| Scraping failure | `WorkdayClient.fetch_jobs()` via `WebScraper` | Caught, logged as error, returns `[]` |

**Pattern:** Greenhouse, Lever, and Ashby let HTTP errors propagate (caller handles retry). Workday catches all exceptions and returns empty list (graceful degradation, since scraping is inherently less reliable).

## Testing

### Test file

`tests/unit/tools/test_ats_clients.py` -- Tests detection regex and slug extraction for all four clients.

| Test Class | Tests |
|------------|-------|
| `TestGreenhouseClient` | `test_detect_greenhouse_url`, `test_detect_non_greenhouse`, `test_extract_slug`, `test_extract_slug_no_match` |
| `TestLeverClient` | `test_detect_lever_url`, `test_detect_non_lever` |
| `TestAshbyClient` | `test_detect_ashby_url`, `test_detect_non_ashby` |
| `TestWorkdayClient` | `test_detect_workday_url`, `test_detect_non_workday` |

### Fixture JSON files in `tests/fixtures/ats_responses/`

| File | Structure | Used by |
|------|-----------|---------|
| `greenhouse_jobs.json` | `{"jobs": [{"id": 100001, "title": "Senior Backend Engineer", ...}, ...]}` | `FakeGreenhouseClient`, `FakeAshbyClient` pattern |
| `lever_jobs.json` | `[{"id": "lever-200001", "text": "Data Engineer", ...}]` | `FakeLeverClient` |
| `ashby_jobs.json` | `{"jobs": [{"id": "ashby-300001", "title": "Full Stack Engineer", ...}]}` | `FakeAshbyClient` |

No fixture file exists for Workday (it returns `[]` in the fake).

### Fake implementations in `tests/mocks/mock_tools.py`

| Fake Class | `detect()` behavior | `fetch_jobs()` behavior |
|------------|---------------------|------------------------|
| `FakeGreenhouseClient` | Uses real regex `r"boards\.greenhouse\.io/(\w+)"` | Loads `greenhouse_jobs.json`, returns `data["jobs"]` |
| `FakeLeverClient` | Uses real regex `r"jobs\.lever\.co/(\w[\w-]*)"` | Loads `lever_jobs.json`, returns direct list |
| `FakeAshbyClient` | Uses real regex `r"jobs\.ashbyhq\.com/(\w[\w-]*)"` | Loads `ashby_jobs.json`, returns `data["jobs"]` |
| `FakeWorkdayClient` | Uses real regex `r"myworkdayjobs\.com\|workday\.com/en-US"` | Returns `[]` |

All fake `detect()` methods use the same regex as the real clients to keep detection behavior consistent in dry-run mode.

## Common Modification Patterns

### Add a new ATS client (step-by-step checklist)

This is the most common extension task. Follow every step.

**1. Add ATSType enum value:**
- File: `src/job_hunter_core/models/company.py`
- Add `NEW_ATS = "new_ats"` to the `ATSType(StrEnum)` enum
- Existing values: `GREENHOUSE`, `LEVER`, `WORKDAY`, `ASHBY`, `ICIMS`, `TALEO`, `CUSTOM`, `UNKNOWN`
- If the value already exists (e.g., `ICIMS`, `TALEO`), skip this step

**2. Create the client implementation:**
- File: `src/job_hunter_agents/tools/ats_clients/<name>.py`
- Follow the pattern of `greenhouse.py` (for API-based) or `workday.py` (for scrape-based):

```python
"""<Name> ATS client."""
from __future__ import annotations
import re
import httpx
import structlog
from job_hunter_agents.tools.ats_clients.base import BaseATSClient
from job_hunter_core.models.company import Company

logger = structlog.get_logger()

<NAME>_PATTERN = re.compile(r"<regex_for_url_detection>", re.IGNORECASE)
<NAME>_API_URL = "https://api.<name>.com/v1/jobs/{slug}"

class <Name>Client(BaseATSClient):
    """Client for <Name> ATS public API."""

    async def detect(self, career_url: str) -> bool:
        return bool(<NAME>_PATTERN.search(career_url))

    def _extract_slug(self, career_url: str) -> str | None:
        match = <NAME>_PATTERN.search(career_url)
        return match.group(1) if match else None

    async def fetch_jobs(self, company: Company) -> list[dict]:
        url = str(company.career_page.url)
        slug = self._extract_slug(url)
        if not slug:
            logger.warning("<name>_no_slug", url=url)
            return []
        api_url = <NAME>_API_URL.format(slug=slug)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            data = response.json()
            jobs = data.get("jobs", [])  # adjust for actual API shape
            logger.info("<name>_jobs_fetched", company=company.name, count=len(jobs))
            return jobs
```

**3. Register in `__init__.py` (if using re-exports):**
- File: `src/job_hunter_agents/tools/ats_clients/__init__.py`
- Currently empty; clients are imported directly by agents
- If the project begins using re-exports, add the import here

**4. Wire into CompanyFinderAgent ATS detection:**
- File: `src/job_hunter_agents/agents/company_finder.py`
- Import: `from job_hunter_agents.tools.ats_clients.<name> import <Name>Client`
- Add `<Name>Client()` to the list of ATS clients checked in `_detect_ats()` method
- Map the detected ATS to `ATSType.NEW_ATS` in the company's `CareerPage`

**5. Wire into JobsScraperAgent ATS scraping:**
- File: `src/job_hunter_agents/agents/jobs_scraper.py`
- Import: `from job_hunter_agents.tools.ats_clients.<name> import <Name>Client`
- Add `ATSType.NEW_ATS: <Name>Client()` to the ATS client dispatch map in `_scrape_via_api()`

**6. Create fake implementation:**
- File: `tests/mocks/mock_tools.py`
- Add `Fake<Name>Client` class:

```python
class Fake<Name>Client:
    """Returns fixture <Name> job data."""

    async def detect(self, career_url: str) -> bool:
        import re
        return bool(re.search(r"<same_regex_as_real_client>", career_url, re.IGNORECASE))

    async def fetch_jobs(self, company: object) -> list[dict[str, object]]:
        fixture = FIXTURES_DIR / "ats_responses" / "<name>_jobs.json"
        data = json.loads(fixture.read_text())
        return data["jobs"]  # adjust for actual response shape
```

**7. Add dry-run patches:**
- File: `src/job_hunter_agents/dryrun.py`
- Add two patch blocks (one for `company_finder`, one for `jobs_scraper`):

```python
# In activate_dry_run_patches():
from tests.mocks.mock_tools import Fake<Name>Client

stack.enter_context(
    patch(
        "job_hunter_agents.agents.company_finder.<Name>Client",
        Fake<Name>Client,
    )
)
stack.enter_context(
    patch(
        "job_hunter_agents.agents.jobs_scraper.<Name>Client",
        Fake<Name>Client,
    )
)
```

**8. Add fixture JSON:**
- File: `tests/fixtures/ats_responses/<name>_jobs.json`
- Create a realistic sample response matching the ATS API's actual JSON structure
- Include 1-2 job listings with all key fields populated

**9. Add unit tests:**
- File: `tests/unit/tools/test_ats_clients.py`
- Add a test class:

```python
@pytest.mark.unit
class Test<Name>Client:
    @pytest.mark.asyncio
    async def test_detect_<name>_url(self) -> None:
        client = <Name>Client()
        assert await client.detect("https://<matching-url>") is True

    @pytest.mark.asyncio
    async def test_detect_non_<name>(self) -> None:
        client = <Name>Client()
        assert await client.detect("https://example.com/careers") is False

    def test_extract_slug(self) -> None:
        client = <Name>Client()
        assert client._extract_slug("https://<matching-url>") == "<expected-slug>"

    def test_extract_slug_no_match(self) -> None:
        client = <Name>Client()
        assert client._extract_slug("https://example.com") is None
```

**10. Run validation:**
```bash
make lint   # ruff + mypy pass
make test   # all existing + new tests pass
```

## Cross-References

- **SPEC_01** -- `ATSType` enum in `models/company.py`, `Company` and `CareerPage` models, `ATSDetectionError` exception
- **SPEC_04** -- `dryrun.py` patches all ATS clients for `--dry-run` mode
- **SPEC_06** -- `CompanyFinderAgent` calls `detect()` to identify ATS type; `JobsScraperAgent` calls `fetch_jobs()` to retrieve listings
- **SPEC_07** -- ATS clients are a specialized subset of tools; `WorkdayClient` depends on `WebScraper` from SPEC_07
- **SPEC_11** -- Fake ATS client implementations in `tests/mocks/mock_tools.py`
