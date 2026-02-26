# SPEC_01: Core Models

## Purpose

Foundation layer (`job_hunter_core`) containing all domain models, configuration, interfaces, state management, constants, and exceptions. Every other package depends on this — it has zero internal dependencies.

## Key Files

| File | Primary Exports | Lines |
|------|----------------|-------|
| `src/job_hunter_core/config/settings.py` | `Settings` | 237 |
| `src/job_hunter_core/models/candidate.py` | `Skill`, `Education`, `CandidateProfile`, `SearchPreferences` | 116 |
| `src/job_hunter_core/models/company.py` | `ATSType`, `CareerPage`, `Company` | 58 |
| `src/job_hunter_core/models/job.py` | `RawJob`, `NormalizedJob`, `FitReport`, `ScoredJob` | 103 |
| `src/job_hunter_core/models/run.py` | `RunConfig`, `AgentError`, `PipelineCheckpoint`, `RunResult` | 77 |
| `src/job_hunter_core/state.py` | `PipelineState` | 158 |
| `src/job_hunter_core/interfaces/cache.py` | `CacheClient` (Protocol) | 27 |
| `src/job_hunter_core/interfaces/embedder.py` | `EmbedderBase` (Protocol) | 19 |
| `src/job_hunter_core/interfaces/search.py` | `SearchProvider` (Protocol), `SearchResult` | 42 |
| `src/job_hunter_core/interfaces/scraper.py` | `PageScraper` (Protocol) | 30 |
| `src/job_hunter_core/interfaces/repository.py` | `BaseRepository[T]` (Protocol) | 30 |
| `src/job_hunter_core/constants.py` | `TOKEN_PRICES`, `SCORING_WEIGHTS`, `COMMON_CAREER_PATHS`, etc. | 56 |
| `src/job_hunter_core/exceptions.py` | `JobHunterError` + 9 subclasses | 48 |

## Public API

### Settings (`config/settings.py`)

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JH_", env_file=".env")
```

**LLM:**
- `anthropic_api_key: SecretStr` — required
- `haiku_model: str = "claude-haiku-4-5-20251001"`
- `sonnet_model: str = "claude-sonnet-4-5-20250514"`

**Search:**
- `tavily_api_key: SecretStr` — required
- `search_provider: Literal["tavily", "duckduckgo"] = "tavily"` — search backend selection; `"duckduckgo"` is free (no API key) and used in integration tests

**Database:**
- `db_backend: Literal["postgres", "sqlite"] = "sqlite"`
- `database_url: str = "sqlite+aiosqlite:///./job_hunter.db"`
- `postgres_url: str = "postgresql+asyncpg://postgres:dev@localhost:5432/jobhunter"`

**Embeddings:**
- `embedding_provider: Literal["voyage", "local"] = "local"`
- `voyage_api_key: SecretStr | None = None`
- `embedding_model: str = "all-MiniLM-L6-v2"`
- `embedding_dimension: int = 384` (auto-set to 1024 for Voyage)

**Cache:**
- `cache_backend: Literal["redis", "db"] = "redis"`
- `redis_url: str = "redis://localhost:6379/0"`
- `cache_ttl_hours: int = 24`
- `company_cache_ttl_days: int = 7`

**Email:**
- `email_provider: Literal["sendgrid", "smtp"] = "smtp"`
- `sendgrid_api_key: SecretStr | None = None`
- `smtp_host: str = "smtp.gmail.com"`, `smtp_port: int = 587`
- `smtp_user: str = ""`, `smtp_password: SecretStr | None = None`

**LangSmith:**
- `langsmith_api_key: SecretStr | None = None`
- `langsmith_project: str = "job-hunter-agent"`

**Observability:**
- `log_format: Literal["json", "console"] = "console"`
- `log_level: str = "INFO"`
- `otel_exporter: Literal["none", "console", "otlp"] = "none"`
- `otel_endpoint: str = "http://localhost:4317"`
- `otel_service_name: str = "job-hunter-agent"`

**Scraping:**
- `max_concurrent_scrapers: int = 5`
- `scrape_timeout_seconds: int = 30`
- `scraper_retry_max: int = 3`
- `scraper_retry_wait_min: float = 1.0`, `scraper_retry_wait_max: float = 10.0`

**Scoring:**
- `min_score_threshold: int = 60`
- `top_k_semantic: int = 50`
- `max_jobs_per_company: int = 10`

**Run:**
- `output_dir: Path = Path("./output")`
- `run_id_prefix: str = "run"`
- `checkpoint_enabled: bool = True`
- `checkpoint_dir: Path = Path("./output/checkpoints")`
- `agent_timeout_seconds: int = 300`

**Cost Guardrails:**
- `max_cost_per_run_usd: float = 5.0`
- `warn_cost_threshold_usd: float = 2.0`

**Validators:**
- `validate_db_config()` — sets `database_url` from `postgres_url` when `db_backend="postgres"`
- `validate_cache_config()` — requires `redis_url` when `cache_backend="redis"`
- `validate_embedding_config()` — requires `voyage_api_key` when `embedding_provider="voyage"`, auto-sets dimension to 1024

---

### Candidate Models (`models/candidate.py`)

```python
class Skill(BaseModel):
    name: str
    level: Literal["beginner", "intermediate", "advanced", "expert"] | None = None
    years: float | None = None

class Education(BaseModel):
    degree: str | None = None
    field: str | None = None
    institution: str | None = None
    graduation_year: int | None = None  # validated: 1950-2030

class CandidateProfile(BaseModel):
    name: str
    email: EmailStr
    phone: str | None = None
    location: str | None = None
    linkedin_url: HttpUrl | None = None
    github_url: HttpUrl | None = None
    current_title: str | None = None
    years_of_experience: float  # ge=0
    skills: list[Skill]
    past_titles: list[str] = []
    industries: list[str] = []
    education: list[Education] = []
    seniority_level: Literal["intern","junior","mid","senior","staff","principal","director","vp","c-level"] | None = None
    tech_stack: list[str] = []
    raw_text: str
    parsed_at: datetime  # defaults to now(UTC)
    content_hash: str  # SHA-256 of raw_text

class SearchPreferences(BaseModel):
    preferred_locations: list[str] = []
    remote_preference: Literal["onsite", "hybrid", "remote", "any"] = "any"
    target_titles: list[str] = []
    target_seniority: list[str] = []
    excluded_titles: list[str] = []
    org_types: list[str] = ["any"]
    company_sizes: list[Literal["1-10","11-50","51-200","201-500","501-1000","1001+"]] = []
    preferred_industries: list[str] = []
    excluded_companies: list[str] = []
    preferred_companies: list[str] = []
    min_salary: int | None = None
    max_salary: int | None = None  # validated: min <= max
    currency: str = "USD"
    raw_text: str
```

---

### Company Models (`models/company.py`)

```python
class ATSType(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    ASHBY = "ashby"
    ICIMS = "icims"
    TALEO = "taleo"
    CUSTOM = "custom"
    UNKNOWN = "unknown"

class CareerPage(BaseModel):
    url: HttpUrl
    ats_type: ATSType = ATSType.UNKNOWN
    api_endpoint: HttpUrl | None = None
    last_scraped_at: datetime | None = None
    scrape_strategy: Literal["api", "crawl4ai", "playwright", "tavily"] = "crawl4ai"

class Company(BaseModel):
    id: UUID = uuid4()
    name: str
    domain: str  # e.g. "stripe.com"
    career_page: CareerPage
    industry: str | None = None
    size: str | None = None
    org_type: str | None = None
    description: str | None = None
    source_confidence: float = 1.0  # 0.0-1.0
```

---

### Job Models (`models/job.py`)

```python
class RawJob(BaseModel):
    id: UUID = uuid4()
    company_id: UUID
    company_name: str
    raw_html: str | None = None
    raw_json: dict[str, object] | None = None
    source_url: HttpUrl
    scraped_at: datetime  # defaults now(UTC)
    scrape_strategy: str
    source_confidence: float  # 0.0-1.0

class NormalizedJob(BaseModel):
    id: UUID = uuid4()
    raw_job_id: UUID
    company_id: UUID
    company_name: str
    title: str
    jd_text: str
    apply_url: HttpUrl
    location: str | None = None
    remote_type: Literal["onsite", "hybrid", "remote", "unknown"] = "unknown"
    posted_date: date | None = None
    salary_min: int | None = None
    salary_max: int | None = None  # validated: min <= max
    currency: str | None = None
    required_skills: list[str] = []
    preferred_skills: list[str] = []
    required_experience_years: float | None = None
    seniority_level: str | None = None
    department: str | None = None
    content_hash: str  # SHA-256 of company_name + title + jd_text[:500]
    processed_at: datetime  # defaults now(UTC)
    embedding: list[float] | None = None

class FitReport(BaseModel):
    score: int  # 0-100
    skill_overlap: list[str]
    skill_gaps: list[str]
    seniority_match: bool
    location_match: bool
    org_type_match: bool
    summary: str
    recommendation: Literal["strong_match", "good_match", "stretch", "mismatch"]
    confidence: float  # 0.0-1.0

class ScoredJob(BaseModel):
    job: NormalizedJob
    fit_report: FitReport
    rank: int | None = None
    scored_at: datetime  # defaults now(UTC)
```

---

### Run Models (`models/run.py`)

```python
class RunConfig(BaseModel):
    run_id: str  # auto: "run_YYYYMMDD_HHMMSS"
    resume_path: Path
    preferences_text: str
    dry_run: bool = False
    force_rescrape: bool = False
    company_limit: int | None = None
    output_formats: list[str] = ["xlsx", "csv"]
    lite_mode: bool = False

class AgentError(BaseModel):
    agent_name: str
    error_type: str  # exception class name
    error_message: str
    company_name: str | None = None
    job_id: UUID | None = None
    timestamp: datetime  # defaults now(UTC)
    is_fatal: bool = False

class PipelineCheckpoint(BaseModel):
    run_id: str
    completed_step: str
    state_snapshot: dict[str, object]  # serialized PipelineState
    saved_at: datetime  # defaults now(UTC)

class RunResult(BaseModel):
    run_id: str
    status: Literal["success", "partial", "failed"]
    companies_attempted: int
    companies_succeeded: int
    jobs_scraped: int
    jobs_scored: int
    jobs_in_output: int
    output_files: list[Path]
    email_sent: bool
    errors: list[AgentError]
    total_tokens_used: int
    estimated_cost_usd: float
    duration_seconds: float
    completed_at: datetime  # defaults now(UTC)
```

---

### PipelineState (`state.py`)

```python
@dataclass
class PipelineState:
    config: RunConfig

    # Step outputs (populated sequentially by agents)
    profile: CandidateProfile | None = None
    preferences: SearchPreferences | None = None
    companies: list[Company] = []
    raw_jobs: list[RawJob] = []
    normalized_jobs: list[NormalizedJob] = []
    scored_jobs: list[ScoredJob] = []

    # Cross-cutting
    errors: list[AgentError] = []
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    run_result: RunResult | None = None

    def to_checkpoint(self, step_name: str) -> PipelineCheckpoint
    @classmethod
    def from_checkpoint(cls, checkpoint: PipelineCheckpoint) -> PipelineState
    @property
    def completed_steps(self) -> list[str]  # infers from populated fields
    def build_result(self, status, duration_seconds, output_files, email_sent) -> RunResult
```

**Completed steps inference:** `profile` -> "parse_resume", `preferences` -> "parse_prefs", `companies` -> "find_companies", `raw_jobs` -> "scrape_jobs", `normalized_jobs` -> "process_jobs", `scored_jobs` -> "score_jobs", `run_result` -> ["aggregate", "notify"]

**Serialization:** `to_checkpoint` calls `model_dump_json()` on each Pydantic model, producing a flat JSON snapshot. `from_checkpoint` reconstructs by passing dicts to model constructors.

---

### Interfaces (Protocols)

```python
# interfaces/cache.py
@runtime_checkable
class CacheClient(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_seconds: int = 86400) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...

# interfaces/embedder.py
@runtime_checkable
class EmbedderBase(Protocol):
    async def embed_text(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

# interfaces/search.py
@runtime_checkable
class SearchProvider(Protocol):
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]: ...
    async def find_career_page(self, company_name: str) -> str | None: ...
    async def search_jobs_on_site(self, domain: str, role_query: str, max_results: int = 10) -> list[SearchResult]: ...

# interfaces/scraper.py
@runtime_checkable
class PageScraper(Protocol):
    async def fetch_page(self, url: str) -> str: ...
    async def fetch_page_playwright(self, url: str) -> str: ...
    async def fetch_json_api(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]: ...

# interfaces/repository.py
@runtime_checkable
class BaseRepository(Protocol[T]):
    async def get_by_id(self, entity_id: UUID) -> T | None: ...
    async def create(self, entity: T) -> T: ...
    async def upsert(self, entity: T) -> T: ...
    async def list_all(self, limit: int = 100, offset: int = 0) -> list[T]: ...
```

---

### Constants (`constants.py`)

| Constant | Type | Purpose |
|----------|------|---------|
| `RESUME_PARSER_PROMPT_VERSION` | `str = "v1"` | Prompt versioning for cache invalidation |
| `PREFS_PARSER_PROMPT_VERSION` | `str = "v1"` | " |
| `COMPANY_FINDER_PROMPT_VERSION` | `str = "v1"` | " |
| `JOB_PROCESSOR_PROMPT_VERSION` | `str = "v1"` | " |
| `JOB_SCORER_PROMPT_VERSION` | `str = "v1"` | " |
| `TOKEN_PRICES` | `dict[str, dict[str, float]]` | USD per 1M tokens (input/output) per model |
| `COMMON_CAREER_PATHS` | `list[str]` | 7 fallback URL paths to try (/careers, /jobs, etc.) |
| `EXCHANGE_RATES_TO_USD` | `dict[str, float]` | 10 currency conversions to USD |
| `SCORING_WEIGHTS` | `dict[str, float]` | 6 dimensions: skill_match(30%), seniority(20%), location(15%), org_type(15%), growth_stage(10%), compensation_fit(10%) |
| `DEFAULT_RATE_LIMIT_PER_DOMAIN` | `int = 3` | Requests per minute per domain |
| `DEFAULT_CONCURRENCY_LIMIT` | `int = 5` | Max concurrent operations |

---

### Exception Hierarchy (`exceptions.py`)

```
JobHunterError (base)
├── CostLimitExceededError     — cost guardrail exceeded (pipeline stops)
├── FatalAgentError            — unrecoverable agent failure (pipeline stops)
├── ScannedPDFError            — PDF has no text layer
├── EncryptedPDFError          — PDF is password-protected
├── InvalidFileError           — file is not a valid PDF
├── ATSDetectionError          — ATS type cannot be determined
├── ScrapingError              — page scraping failed after all fallbacks
├── EmbeddingError             — text embedding failed
├── EmailDeliveryError         — email sending failed
└── CheckpointError            — checkpoint save/load failed
```

**Pipeline-stopping exceptions:** `CostLimitExceededError`, `FatalAgentError` — caught by Pipeline.run() and returned in RunResult.

## Internal Dependencies

None. This is the leaf package — all other packages import from here.

## External Dependencies

- `pydantic>=2.0` — model definitions, validation
- `pydantic-settings>=2.0` — Settings with env var loading
- `email-validator>=2.0` — `EmailStr` validation

## Data Flow

```
Settings (loaded once at startup)
    ↓
RunConfig (created from CLI args)
    ↓
PipelineState (initialized with RunConfig)
    ↓ (populated sequentially by each agent)
    profile → preferences → companies → raw_jobs → normalized_jobs → scored_jobs
    ↓
RunResult (built at pipeline end from accumulated state)
```

## Configuration

All 40+ fields listed in the Settings section above. Every field has a `JH_` env prefix (e.g., `JH_ANTHROPIC_API_KEY`, `JH_DB_BACKEND`).

## Error Handling

- All custom exceptions inherit from `JobHunterError` for catch-all handling
- `CostLimitExceededError` and `FatalAgentError` stop the pipeline
- Other exceptions are caught per-agent and recorded as `AgentError` in state
- Pydantic `ValidationError` raised for invalid model data (salary range, graduation year)

## Testing

| Test File | What It Tests |
|-----------|--------------|
| `tests/unit/core/test_candidate.py` | CandidateProfile, SearchPreferences, Skill, Education validation |
| `tests/unit/core/test_company.py` | Company, CareerPage, ATSType serialization |
| `tests/unit/core/test_job.py` | RawJob, NormalizedJob, FitReport, ScoredJob validation |
| `tests/unit/core/test_run.py` | RunConfig defaults, RunResult, AgentError, PipelineCheckpoint |
| `tests/unit/core/test_settings.py` | Settings validators, env prefix, defaults |
| `tests/unit/core/test_state.py` | PipelineState to_checkpoint, from_checkpoint, completed_steps, build_result |

**Key factories:** `make_candidate_profile()`, `make_search_preferences()`, `make_company()`, `make_raw_job()`, `make_normalized_job()`, `make_scored_job()`, `make_run_config()`, `make_pipeline_state()`, `make_agent_error()` — all in `tests/mocks/mock_factories.py`

## Common Modification Patterns

### Add a new field to a domain model
1. Add the field to the Pydantic model in `models/*.py`
2. If needed, add a validator (`@model_validator`)
3. Update `PipelineState.to_checkpoint()` and `from_checkpoint()` if the model is directly on state
4. Update the factory function in `tests/mocks/mock_factories.py`
5. Update the corresponding ORM model in `job_hunter_infra/db/models.py` (see SPEC_02)
6. Run `make lint && make test`

### Add a new Settings field
1. Add the field to `Settings` class with `Field(default=..., description=...)`
2. Add the env var (with `JH_` prefix) to `.env.example`
3. Add the field to `make_settings()` in `tests/mocks/mock_settings.py`
4. If it needs validation, add a `@model_validator`

### Add a new exception type
1. Add a class inheriting from `JobHunterError` in `exceptions.py`
2. If pipeline-stopping, add handling in `Pipeline._run_agent_step()` (see SPEC_04)

## Cross-References

- **SPEC_02** — ORM models mirror these domain models
- **SPEC_04** — Pipeline and BaseAgent consume PipelineState, RunConfig, exceptions
- **SPEC_05/06/09** — Agents produce/consume these models
- **SPEC_10** — Cost tracking uses TOKEN_PRICES
- **SPEC_11** — Mock factories create instances of all these models
