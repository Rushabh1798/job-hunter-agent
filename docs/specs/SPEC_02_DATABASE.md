# SPEC_02: Database

## Purpose

Persistence layer (`job_hunter_infra.db`) providing async SQLAlchemy ORM table definitions, a backend-agnostic engine factory (PostgreSQL or SQLite), session management, and repository classes for all CRUD operations. This layer sits between the domain models defined in `job_hunter_core` and the underlying relational database, enforcing schema constraints and providing a clean data access interface to agents and the pipeline orchestrator.

## Key Files

| File | Primary Exports | Lines |
|------|----------------|-------|
| `src/job_hunter_infra/db/models.py` | `Base`, `ProfileModel`, `CompanyModel`, `RawJobModel`, `NormalizedJobModel`, `ScoredJobModel`, `RunHistoryModel` | 196 |
| `src/job_hunter_infra/db/engine.py` | `create_engine()` | 23 |
| `src/job_hunter_infra/db/session.py` | `create_session_factory()`, `init_db()`, `get_session()` | 28 |
| `src/job_hunter_infra/db/repositories/profile_repo.py` | `ProfileRepository` | 44 |
| `src/job_hunter_infra/db/repositories/company_repo.py` | `CompanyRepository` | 49 |
| `src/job_hunter_infra/db/repositories/job_repo.py` | `JobRepository` | 61 |
| `src/job_hunter_infra/db/repositories/score_repo.py` | `ScoreRepository` | 33 |
| `src/job_hunter_infra/db/repositories/run_repo.py` | `RunRepository` | 34 |
| `src/job_hunter_infra/db/repositories/__init__.py` | _(empty)_ | 1 |
| `src/job_hunter_infra/db/__init__.py` | _(empty)_ | 1 |

## Public API

### ORM Base Class (`models.py`)

```python
class Base(DeclarativeBase):
    """Base class for all ORM models. Provides metadata registry."""
```

All ORM models inherit from `Base`. `Base.metadata` is used by `init_db()` to create tables and by Alembic for migration autogeneration.

---

### ProfileModel (`models.py`) -- Table: `profiles`

Stores parsed candidate resume data. Each unique resume (by content hash) maps to one row.

| Column | SQLAlchemy Type | Python Type | Nullable | Constraints | Default |
|--------|----------------|-------------|----------|-------------|---------|
| `id` | `String(36)` | `str` | No | **PRIMARY KEY** | `lambda: str(uuid4())` |
| `content_hash` | `String(64)` | `str` | No | **UNIQUE** | -- |
| `email` | `String(255)` | `str` | No | -- | -- |
| `name` | `String(255)` | `str` | No | -- | -- |
| `phone` | `String(50)` | `str \| None` | Yes | -- | `None` |
| `location` | `String(255)` | `str \| None` | Yes | -- | `None` |
| `current_title` | `String(255)` | `str \| None` | Yes | -- | `None` |
| `years_of_experience` | `Float` | `float` | No | -- | -- |
| `seniority_level` | `String(50)` | `str \| None` | Yes | -- | `None` |
| `skills_json` | `JSON` | `dict` | No | -- | -- |
| `education_json` | `JSON` | `dict \| None` | Yes | -- | `None` |
| `past_titles_json` | `JSON` | `dict \| None` | Yes | -- | `None` |
| `industries_json` | `JSON` | `dict \| None` | Yes | -- | `None` |
| `tech_stack_json` | `JSON` | `dict \| None` | Yes | -- | `None` |
| `raw_text` | `Text` | `str` | No | -- | -- |
| `created_at` | `DateTime` | `datetime` | No | -- | `lambda: datetime.now(UTC)` |
| `updated_at` | `DateTime` | `datetime` | No | -- | `lambda: datetime.now(UTC)`, **onupdate** `lambda: datetime.now(UTC)` |

**Indexes:** Implicit unique index on `content_hash`.

**Notes:**
- `skills_json` typically stores `list[dict]` with `{"name": str, ...}` entries (matches domain `Skill` model).
- `education_json`, `past_titles_json`, `industries_json`, `tech_stack_json` store serialized lists/dicts from the domain `CandidateProfile`.
- `content_hash` is SHA-256 hex digest of the raw resume text, used for deduplication.

---

### CompanyModel (`models.py`) -- Table: `companies`

Stores discovered companies and their career page metadata.

| Column | SQLAlchemy Type | Python Type | Nullable | Constraints | Default |
|--------|----------------|-------------|----------|-------------|---------|
| `id` | `String(36)` | `str` | No | **PRIMARY KEY** | `lambda: str(uuid4())` |
| `name` | `String(255)` | `str` | No | -- | -- |
| `domain` | `String(255)` | `str` | No | **INDEX** | -- |
| `ats_type` | `String(50)` | `str` | No | -- | `"unknown"` |
| `career_url` | `String(1024)` | `str` | No | -- | -- |
| `api_endpoint` | `String(1024)` | `str \| None` | Yes | -- | `None` |
| `industry` | `String(255)` | `str \| None` | Yes | -- | `None` |
| `size` | `String(50)` | `str \| None` | Yes | -- | `None` |
| `org_type` | `String(100)` | `str \| None` | Yes | -- | `None` |
| `description` | `Text` | `str \| None` | Yes | -- | `None` |
| `source_confidence` | `Float` | `float` | No | -- | `1.0` |
| `scrape_strategy` | `String(50)` | `str` | No | -- | `"crawl4ai"` |
| `last_scraped_at` | `DateTime` | `datetime \| None` | Yes | -- | `None` |
| `created_at` | `DateTime` | `datetime` | No | -- | `lambda: datetime.now(UTC)` |
| `updated_at` | `DateTime` | `datetime` | No | -- | `lambda: datetime.now(UTC)`, **onupdate** `lambda: datetime.now(UTC)` |

**Indexes:** Explicit index on `domain`.

**Notes:**
- `ats_type` values correspond to `ATSType` enum in core: `"greenhouse"`, `"lever"`, `"ashby"`, `"workday"`, `"unknown"`.
- `scrape_strategy` tracks how the career page was scraped: `"crawl4ai"`, `"api"`, etc.
- `domain` is the natural lookup key (used by `CompanyRepository.get_by_domain` and upsert logic), but does **not** have a UNIQUE constraint at the DB level -- uniqueness is enforced at the application level via the upsert pattern.

---

### RawJobModel (`models.py`) -- Table: `jobs_raw`

Stores raw scraped job data before normalization. One row per scraped job posting.

| Column | SQLAlchemy Type | Python Type | Nullable | Constraints | Default |
|--------|----------------|-------------|----------|-------------|---------|
| `id` | `String(36)` | `str` | No | **PRIMARY KEY** | `lambda: str(uuid4())` |
| `company_id` | `String(36)` | `str` | No | **FOREIGN KEY** -> `companies.id` | -- |
| `source_url` | `String(2048)` | `str` | No | -- | -- |
| `raw_html` | `Text` | `str \| None` | Yes | -- | `None` |
| `raw_json` | `JSON` | `dict \| None` | Yes | -- | `None` |
| `scrape_strategy` | `String(50)` | `str` | No | -- | -- |
| `source_confidence` | `Float` | `float` | No | -- | `1.0` |
| `scraped_at` | `DateTime` | `datetime` | No | -- | `lambda: datetime.now(UTC)` |
| `created_at` | `DateTime` | `datetime` | No | -- | `lambda: datetime.now(UTC)` |

**Foreign Keys:** `company_id` -> `companies.id` (default ON DELETE behavior -- no cascade specified, so DB-level default applies).

**Notes:**
- A raw job stores either HTML (`raw_html` from crawl4ai scraping) or JSON (`raw_json` from ATS API responses), or both.
- No `updated_at` column -- raw jobs are write-once records.

---

### NormalizedJobModel (`models.py`) -- Table: `jobs_normalized`

Stores structured, deduplicated job listings after LLM normalization. This is the primary table for scoring and output.

| Column | SQLAlchemy Type | Python Type | Nullable | Constraints | Default |
|--------|----------------|-------------|----------|-------------|---------|
| `id` | `String(36)` | `str` | No | **PRIMARY KEY** | `lambda: str(uuid4())` |
| `raw_job_id` | `String(36)` | `str \| None` | Yes | **FOREIGN KEY** -> `jobs_raw.id` | `None` |
| `company_id` | `String(36)` | `str` | No | **FOREIGN KEY** -> `companies.id` | -- |
| `company_name` | `String(255)` | `str` | No | -- | -- |
| `title` | `String(500)` | `str` | No | -- | -- |
| `jd_text` | `Text` | `str` | No | -- | -- |
| `apply_url` | `String(2048)` | `str` | No | -- | -- |
| `location` | `String(255)` | `str \| None` | Yes | -- | `None` |
| `remote_type` | `String(50)` | `str` | No | -- | `"unknown"` |
| `posted_date` | `Date` | `datetime \| None` | Yes | -- | `None` |
| `salary_min` | `Integer` | `int \| None` | Yes | -- | `None` |
| `salary_max` | `Integer` | `int \| None` | Yes | -- | `None` |
| `currency` | `String(10)` | `str \| None` | Yes | -- | `None` |
| `required_skills_json` | `JSON` | `dict \| None` | Yes | -- | `None` |
| `preferred_skills_json` | `JSON` | `dict \| None` | Yes | -- | `None` |
| `required_experience_years` | `Float` | `float \| None` | Yes | -- | `None` |
| `seniority_level` | `String(50)` | `str \| None` | Yes | -- | `None` |
| `department` | `String(255)` | `str \| None` | Yes | -- | `None` |
| `content_hash` | `String(64)` | `str` | No | **UNIQUE**, **INDEX** | -- |
| `embedding_json` | `Text` | `str \| None` | Yes | -- | `None` |
| `processed_at` | `DateTime` | `datetime` | No | -- | `lambda: datetime.now(UTC)` |
| `created_at` | `DateTime` | `datetime` | No | -- | `lambda: datetime.now(UTC)` |
| `updated_at` | `DateTime` | `datetime` | No | -- | `lambda: datetime.now(UTC)`, **onupdate** `lambda: datetime.now(UTC)` |

**Indexes:** Explicit unique index on `content_hash`.

**Foreign Keys:**
- `raw_job_id` -> `jobs_raw.id` (nullable -- normalized jobs can exist without a raw counterpart if created directly from ATS API data).
- `company_id` -> `companies.id`.

**Notes:**
- `content_hash` is SHA-256 hex digest of the normalized job content, used for deduplication across scraping runs.
- `embedding_json` stores the embedding vector as a JSON-serialized `list[float]` string. Used for brute-force cosine similarity in SQLite mode. In PostgreSQL mode, pgvector columns would be used instead (not yet implemented in the ORM -- deferred to post-MVP).
- `posted_date` uses `Date` type (not `DateTime`), storing only the date portion.
- `remote_type` values: `"remote"`, `"hybrid"`, `"onsite"`, `"unknown"`.

---

### ScoredJobModel (`models.py`) -- Table: `jobs_scored`

Stores LLM-generated scoring results for each job per pipeline run.

| Column | SQLAlchemy Type | Python Type | Nullable | Constraints | Default |
|--------|----------------|-------------|----------|-------------|---------|
| `id` | `String(36)` | `str` | No | **PRIMARY KEY** | `lambda: str(uuid4())` |
| `normalized_job_id` | `String(36)` | `str` | No | **FOREIGN KEY** -> `jobs_normalized.id` | -- |
| `run_id` | `String(100)` | `str` | No | **INDEX** | -- |
| `score` | `Integer` | `int` | No | -- | -- |
| `skill_overlap_json` | `JSON` | `dict \| None` | Yes | -- | `None` |
| `skill_gaps_json` | `JSON` | `dict \| None` | Yes | -- | `None` |
| `seniority_match` | `Boolean` | `bool \| None` | Yes | -- | `None` |
| `location_match` | `Boolean` | `bool \| None` | Yes | -- | `None` |
| `org_type_match` | `Boolean` | `bool \| None` | Yes | -- | `None` |
| `fit_summary` | `Text` | `str \| None` | Yes | -- | `None` |
| `recommendation` | `String(50)` | `str \| None` | Yes | -- | `None` |
| `confidence` | `Float` | `float \| None` | Yes | -- | `None` |
| `rank` | `Integer` | `int \| None` | Yes | -- | `None` |
| `scored_at` | `DateTime` | `datetime` | No | -- | `lambda: datetime.now(UTC)` |
| `created_at` | `DateTime` | `datetime` | No | -- | `lambda: datetime.now(UTC)` |

**Indexes:** Explicit index on `run_id`.

**Foreign Keys:** `normalized_job_id` -> `jobs_normalized.id`.

**Notes:**
- `score` is an integer 0-100 representing overall fit.
- `recommendation` values: `"strong_apply"`, `"apply"`, `"maybe"`, `"skip"` (matches domain `FitReport` recommendation field).
- `confidence` is a float 0.0-1.0 representing the LLM's confidence in the score.
- `rank` is the position in the final sorted output (1 = best match).
- No `updated_at` -- scored jobs are write-once records per run.
- The same `normalized_job_id` can appear multiple times across different `run_id` values (rescoring across runs).

---

### RunHistoryModel (`models.py`) -- Table: `run_history`

Stores metadata and metrics for each pipeline execution run.

| Column | SQLAlchemy Type | Python Type | Nullable | Constraints | Default |
|--------|----------------|-------------|----------|-------------|---------|
| `id` | `String(36)` | `str` | No | **PRIMARY KEY** | `lambda: str(uuid4())` |
| `run_id` | `String(100)` | `str` | No | **UNIQUE**, **INDEX** | -- |
| `status` | `String(50)` | `str` | No | -- | -- |
| `companies_attempted` | `Integer` | `int` | No | -- | `0` |
| `companies_succeeded` | `Integer` | `int` | No | -- | `0` |
| `jobs_scraped` | `Integer` | `int` | No | -- | `0` |
| `jobs_scored` | `Integer` | `int` | No | -- | `0` |
| `jobs_in_output` | `Integer` | `int` | No | -- | `0` |
| `output_files_json` | `JSON` | `dict \| None` | Yes | -- | `None` |
| `email_sent` | `Boolean` | `bool` | No | -- | `False` |
| `tokens_used` | `Integer` | `int` | No | -- | `0` |
| `cost_usd` | `Float` | `float` | No | -- | `0.0` |
| `duration_seconds` | `Float` | `float \| None` | Yes | -- | `None` |
| `errors_json` | `JSON` | `dict \| None` | Yes | -- | `None` |
| `created_at` | `DateTime` | `datetime` | No | -- | `lambda: datetime.now(UTC)` |

**Indexes:** Explicit unique index on `run_id`.

**Notes:**
- `status` values: `"running"`, `"completed"`, `"failed"`, `"cancelled"`.
- `output_files_json` stores `{"csv": "/path/to.csv", "xlsx": "/path/to.xlsx"}`.
- `errors_json` stores a list of serialized `AgentError` objects from the run.
- No `updated_at` column -- run records are updated in-place by mutating fields and flushing.

---

### Engine Factory (`engine.py`)

```python
def create_engine(settings: Settings) -> AsyncEngine:
    """Create an async SQLAlchemy engine based on settings.

    For sqlite backend:
        - Uses settings.database_url directly
        - Sets echo=False, connect_args={"check_same_thread": False}

    For postgres backend:
        - Uses settings.database_url (auto-set from postgres_url by Settings validator)
        - Sets echo=False, pool_size=5, max_overflow=10
    """
```

**Backend behavior:**

| Backend | Driver | Pool Config | Extra Args |
|---------|--------|-------------|------------|
| `sqlite` | `aiosqlite` | No pool (single connection) | `check_same_thread=False` |
| `postgres` | `asyncpg` | `pool_size=5`, `max_overflow=10` | None |

---

### Session Factory & Helpers (`session.py`)

```python
def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory.
    expire_on_commit=False to allow accessing attributes after commit."""

async def init_db(engine: AsyncEngine) -> None:
    """Create all tables via Base.metadata.create_all.
    Intended for SQLite mode. Use Alembic migrations for PostgreSQL."""

async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session and ensure it's closed on exit.
    Intended for use as a dependency injection generator."""
```

**Session configuration:** `expire_on_commit=False` is set so that ORM model attributes remain accessible after `session.commit()` without triggering lazy loads.

---

### ProfileRepository (`repositories/profile_repo.py`)

```python
class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None: ...

    async def get_by_id(self, profile_id: str) -> ProfileModel | None:
        """Retrieve a profile by primary key. Returns None if not found."""

    async def get_by_content_hash(self, content_hash: str) -> ProfileModel | None:
        """Retrieve a profile by content_hash. Returns None if not found.
        Uses: SELECT ... WHERE content_hash = :hash"""

    async def create(self, model: ProfileModel) -> ProfileModel:
        """Add a new profile to the session and flush.
        Returns the model with its auto-generated id populated."""

    async def upsert(self, model: ProfileModel) -> ProfileModel:
        """Create or update a profile by content_hash.
        - If a profile with the same content_hash exists: updates email, name,
          skills_json, and raw_text on the existing record, then flushes.
        - If no match: delegates to create().
        NOTE: Only updates email, name, skills_json, raw_text — other fields
        (phone, location, current_title, etc.) are NOT updated on upsert."""
```

---

### CompanyRepository (`repositories/company_repo.py`)

```python
class CompanyRepository:
    def __init__(self, session: AsyncSession) -> None: ...

    async def get_by_id(self, company_id: str) -> CompanyModel | None:
        """Retrieve a company by primary key. Returns None if not found."""

    async def get_by_domain(self, domain: str) -> CompanyModel | None:
        """Retrieve a company by domain. Returns None if not found.
        Uses: SELECT ... WHERE domain = :domain"""

    async def create(self, model: CompanyModel) -> CompanyModel:
        """Add a new company to the session and flush.
        Returns the model with its auto-generated id populated."""

    async def upsert(self, model: CompanyModel) -> CompanyModel:
        """Create or update a company by domain.
        - If a company with the same domain exists: updates name, career_url,
          and ats_type on the existing record, then flushes.
        - If no match: delegates to create().
        NOTE: Only updates name, career_url, ats_type — other fields
        (api_endpoint, industry, size, etc.) are NOT updated on upsert."""

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[CompanyModel]:
        """List companies with pagination.
        Uses: SELECT ... LIMIT :limit OFFSET :offset
        No ordering is specified — order is database-dependent."""
```

---

### JobRepository (`repositories/job_repo.py`)

```python
class JobRepository:
    def __init__(self, session: AsyncSession) -> None: ...

    async def create_raw(self, model: RawJobModel) -> RawJobModel:
        """Add a new raw job record and flush. Returns model with id populated."""

    async def create_normalized(self, model: NormalizedJobModel) -> NormalizedJobModel:
        """Add a new normalized job record and flush. Returns model with id populated."""

    async def get_normalized_by_hash(self, content_hash: str) -> NormalizedJobModel | None:
        """Retrieve a normalized job by content_hash. Returns None if not found.
        Uses: SELECT ... WHERE content_hash = :hash"""

    async def upsert_normalized(self, model: NormalizedJobModel) -> NormalizedJobModel:
        """Create or skip (not update) a normalized job by content_hash.
        - If a job with the same content_hash exists: returns the existing record
          WITHOUT updating any fields.
        - If no match: delegates to create_normalized().
        This is a deduplicate-on-insert pattern, not a true upsert."""

    async def list_normalized(self, limit: int = 100, offset: int = 0) -> list[NormalizedJobModel]:
        """List normalized jobs with pagination.
        Uses: SELECT ... LIMIT :limit OFFSET :offset
        No ordering is specified."""

    async def get_all_with_embeddings(self) -> list[tuple[NormalizedJobModel, list[float]]]:
        """Get all normalized jobs that have non-null embedding_json.
        Parses embedding_json (JSON string) into list[float] for each row.
        Used for SQLite brute-force cosine similarity search.
        Uses: SELECT ... WHERE embedding_json IS NOT NULL
        Returns list of (model, embedding_vector) tuples."""
```

---

### ScoreRepository (`repositories/score_repo.py`)

```python
class ScoreRepository:
    def __init__(self, session: AsyncSession) -> None: ...

    async def create(self, model: ScoredJobModel) -> ScoredJobModel:
        """Add a new scored job record and flush. Returns model with id populated."""

    async def list_by_run(self, run_id: str, limit: int = 100) -> list[ScoredJobModel]:
        """List scored jobs for a given run_id, ordered by score descending.
        Uses: SELECT ... WHERE run_id = :run_id ORDER BY score DESC LIMIT :limit"""
```

---

### RunRepository (`repositories/run_repo.py`)

```python
class RunRepository:
    def __init__(self, session: AsyncSession) -> None: ...

    async def create(self, model: RunHistoryModel) -> RunHistoryModel:
        """Add a new run history record and flush. Returns model with id populated."""

    async def get_by_run_id(self, run_id: str) -> RunHistoryModel | None:
        """Retrieve a run by its run_id (not by primary key id).
        Uses: SELECT ... WHERE run_id = :run_id"""

    async def list_recent(self, limit: int = 10) -> list[RunHistoryModel]:
        """List recent runs ordered by created_at descending.
        Uses: SELECT ... ORDER BY created_at DESC LIMIT :limit"""
```

---

## Internal Dependencies

All imports from within the monorepo:

| Source File | Imports From | What |
|-------------|-------------|------|
| `engine.py` | `job_hunter_core.config.settings` | `Settings` (for `db_backend`, `database_url`) |
| `session.py` | `job_hunter_infra.db.models` | `Base` (for `Base.metadata.create_all`) |
| `profile_repo.py` | `job_hunter_infra.db.models` | `ProfileModel` |
| `company_repo.py` | `job_hunter_infra.db.models` | `CompanyModel` |
| `job_repo.py` | `job_hunter_infra.db.models` | `RawJobModel`, `NormalizedJobModel` |
| `score_repo.py` | `job_hunter_infra.db.models` | `ScoredJobModel` |
| `run_repo.py` | `job_hunter_infra.db.models` | `RunHistoryModel` |

**Cross-package dependency:** Only `engine.py` imports from `job_hunter_core` (the `Settings` class). All other files are self-contained within `job_hunter_infra.db`. Repositories import only ORM models from `models.py`, never domain models from `job_hunter_core.models`.

**Relationship to SPEC_01:** The ORM models in `models.py` mirror the domain models from `job_hunter_core.models` (e.g., `CandidateProfile` -> `ProfileModel`, `Company` -> `CompanyModel`, `NormalizedJob` -> `NormalizedJobModel`). Translation between domain models and ORM models happens in the agent/pipeline layer, not in the repositories.

## External Dependencies

| Package | Version Constraint | Usage |
|---------|-------------------|-------|
| `sqlalchemy[asyncio]` | `>=2.0` | ORM, `DeclarativeBase`, `mapped_column`, `async_sessionmaker`, `create_async_engine` |
| `asyncpg` | `>=0.29` | PostgreSQL async driver (used when `db_backend="postgres"`) |
| `aiosqlite` | `>=0.20` | SQLite async driver (used when `db_backend="sqlite"`) |
| `alembic` | `>=1.13` | Database migrations (Postgres mode; not directly imported in these files but used operationally) |
| `pgvector` | `>=0.3` | PostgreSQL vector extension (declared as dependency, not yet used in ORM models) |

**SQLAlchemy imports used across the layer:**
- From `sqlalchemy`: `Boolean`, `Date`, `DateTime`, `Float`, `ForeignKey`, `Integer`, `String`, `Text`, `select`
- From `sqlalchemy.orm`: `DeclarativeBase`, `Mapped`, `mapped_column`
- From `sqlalchemy.types`: `JSON`
- From `sqlalchemy.ext.asyncio`: `AsyncEngine`, `AsyncSession`, `async_sessionmaker`, `create_async_engine`

## Data Flow

### Write Path (e.g., saving a normalized job)

```
Agent produces domain model (NormalizedJob from job_hunter_core.models.job)
    |
    v
Agent/pipeline code translates domain model fields into ORM model kwargs
    |
    v
NormalizedJobModel(...) constructed with column values
    |
    v
JobRepository.upsert_normalized(model) called
    |
    +--> get_normalized_by_hash(content_hash)  -- SELECT to check for duplicates
    |
    +--> If exists: return existing ORM model (skip insert)
    |
    +--> If new: session.add(model) + session.flush()  -- INSERT into jobs_normalized
    |
    v
ORM model returned (with auto-generated id, timestamps)
    |
    v
Caller may access model.id for foreign key references in subsequent inserts
```

### Read Path (e.g., listing scored jobs for output)

```
OutputAgent needs scored jobs for a run_id
    |
    v
ScoreRepository.list_by_run(run_id, limit=100)
    |
    v
SELECT ... FROM jobs_scored WHERE run_id = :run_id ORDER BY score DESC LIMIT 100
    |
    v
SQLAlchemy executes query, maps rows to ScoredJobModel instances
    |
    v
list[ScoredJobModel] returned to caller
    |
    v
Agent/pipeline code reads ORM model attributes (score, fit_summary, etc.)
and translates them into domain models or output format (CSV/Excel)
```

### Session Lifecycle

```
create_engine(settings)         -- once at startup
    |
    v
create_session_factory(engine)  -- once at startup
    |
    v
get_session(factory)            -- per operation (async generator)
    |
    v
Repository(session)             -- repositories are created per-session
    |
    v
repo.create/upsert/list/get    -- operations call session.flush() internally
    |
    v
session.commit()                -- committed by the pipeline/caller, NOT by repositories
    |                              (exception: DBCacheClient commits internally)
    v
session.__aexit__()             -- auto-closed by async context manager
```

**Important:** Repositories call `session.flush()` (writes to DB within the transaction) but do NOT call `session.commit()`. The calling code (pipeline orchestrator) is responsible for committing the transaction. This allows multiple repository operations to be grouped in a single transaction.

## Configuration

### Relevant Settings Fields (from `job_hunter_core.config.settings.Settings`)

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `db_backend` | `Literal["postgres", "sqlite"]` | `"sqlite"` | `JH_DB_BACKEND` | Selects database driver and engine configuration |
| `database_url` | `str` | `"sqlite+aiosqlite:///./job_hunter.db"` | `JH_DATABASE_URL` | SQLAlchemy connection URL (auto-set for postgres) |
| `postgres_url` | `str` | `"postgresql+asyncpg://postgres:dev@localhost:5432/jobhunter"` | `JH_POSTGRES_URL` | PostgreSQL connection string |

### Settings Validator: `validate_db_config`

```python
@model_validator(mode="after")
def validate_db_config(self) -> Settings:
    """When db_backend='postgres', overwrites database_url with postgres_url."""
    if self.db_backend == "postgres":
        self.database_url = self.postgres_url
    return self
```

This means:
- **SQLite mode** (`db_backend="sqlite"`): `database_url` is used as-is. Default creates `./job_hunter.db` in the working directory.
- **PostgreSQL mode** (`db_backend="postgres"`): `database_url` is overwritten with `postgres_url`, regardless of what `database_url` was set to.

### Engine Configuration by Backend

| Parameter | SQLite | PostgreSQL |
|-----------|--------|------------|
| `echo` | `False` | `False` |
| `pool_size` | N/A | `5` |
| `max_overflow` | N/A | `10` |
| `check_same_thread` | `False` | N/A |

## Error Handling

### IntegrityError (Duplicate Keys)

Repositories handle deduplication at the application level via upsert patterns, avoiding `IntegrityError` in normal operation:

| Repository | Method | Strategy |
|-----------|--------|----------|
| `ProfileRepository.upsert()` | SELECT by `content_hash` first, update if exists, create if new | Application-level upsert |
| `CompanyRepository.upsert()` | SELECT by `domain` first, update if exists, create if new | Application-level upsert |
| `JobRepository.upsert_normalized()` | SELECT by `content_hash` first, return existing if found, create if new | Application-level deduplicate (no update) |

If concurrent writes produce an `IntegrityError` (race condition between SELECT and INSERT), it will propagate to the caller. The repositories do NOT catch `IntegrityError` internally. Callers are expected to handle this if concurrent access is possible.

### Connection Errors

No explicit connection error handling exists in the DB layer. Connection failures from `asyncpg` or `aiosqlite` propagate as SQLAlchemy `OperationalError` or driver-specific exceptions. The pipeline orchestrator is responsible for retry/circuit-breaker logic around DB operations.

### Session Errors

`get_session()` uses `async with session_factory() as session:` which automatically closes the session on exit, even if an exception occurs. However, it does NOT handle rollback -- if an exception occurs mid-transaction, the caller must handle rollback or rely on session disposal to discard uncommitted changes.

### Flush vs Commit

All repository write methods call `session.flush()`, which sends SQL to the database within the current transaction but does NOT commit. This means:
- If the caller never calls `session.commit()`, changes are rolled back when the session closes.
- If an error occurs after a flush but before commit, the entire transaction's changes are discarded.
- The `DBCacheClient` (in `cache/db_cache.py`) is an exception -- it calls `session.commit()` directly.

## Testing

### Test Files

| File | Scope | Marker | Database | What's Tested |
|------|-------|--------|----------|---------------|
| `tests/unit/infra/test_repositories.py` | Unit | `@pytest.mark.unit` | In-memory SQLite (`sqlite+aiosqlite://`) | `ProfileRepository` (create, get_by_id, get_by_content_hash, upsert), `CompanyRepository` (create, get_by_domain, list_all) |
| `tests/integration/test_db_repositories.py` | Integration | `@pytest.mark.integration` | Real PostgreSQL (`jobhunter_test` DB) | `ProfileModel` (save/get, unique constraint), `CompanyModel` (save/list, upsert), `NormalizedJobModel` (save raw+normalized, query by company, unique content_hash constraint), `RawJobModel` (foreign key constraint) |

### Unit Test Fixtures

```python
@pytest.fixture
async def session() -> AsyncSession:
    """In-memory SQLite with all tables created via Base.metadata.create_all.
    Yields a session, disposes engine on teardown."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as sess:
        yield sess
    await engine.dispose()
```

Unit tests use the real repository classes against in-memory SQLite. No mocking of the database -- this is a "real DB, cheap DB" strategy.

### Integration Test Fixtures (`tests/integration/conftest.py`)

```python
TEST_DB_URL = "postgresql+asyncpg://postgres:dev@localhost:5432/jobhunter_test"

skip_no_postgres = pytest.mark.skipif(
    not _pg_up,
    reason="PostgreSQL not reachable on localhost:5432 — run `make dev` first",
)
```

- **Session-scoped engine:** Creates the `jobhunter_test` database if it doesn't exist, creates all tables, drops all tables on teardown.
- **Function-scoped session:** Uses savepoint (`begin_nested()`) and rollback to isolate each test. No data leaks between tests.
- **Skip if no Postgres:** Tests are skipped automatically when PostgreSQL is not running on `localhost:5432`.

### Integration Tests -- Direct ORM Usage

Integration tests in `test_db_repositories.py` test constraints and operations directly against ORM models using `session.add()` / `session.flush()` / `session.get()`, rather than going through repository classes. This tests the schema constraints (unique, foreign key) at the database level.

### What's NOT Tested

- `RunRepository` and `ScoreRepository` do not have dedicated test files. Their behavior is implicitly covered by pipeline-level tests.
- `JobRepository.get_all_with_embeddings()` (the embedding JSON parsing path) is not covered by existing tests.
- Engine factory `create_engine()` is not directly tested (tested implicitly through fixtures).
- `init_db()` is tested implicitly by the unit test fixture setup.
- Error handling paths (connection failures, concurrent `IntegrityError`) are not tested.

## Common Modification Patterns

### Add a New DB Table

1. **Define the ORM model** in `src/job_hunter_infra/db/models.py`:

```python
class NewTableModel(Base):
    """Describe what this table stores."""

    __tablename__ = "new_table"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    # ... columns ...
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
```

2. **Create a repository** in `src/job_hunter_infra/db/repositories/new_table_repo.py` following the existing pattern (accept `AsyncSession` in `__init__`, provide typed CRUD methods).

3. **Generate an Alembic migration** (for PostgreSQL):
```bash
uv run alembic revision --autogenerate -m "add_new_table"
uv run alembic upgrade head
```

4. **For SQLite mode:** `init_db()` will automatically create the table via `Base.metadata.create_all`.

5. **Add tests** in `tests/unit/infra/test_repositories.py` and optionally `tests/integration/test_db_repositories.py`.

### Add a Column to an Existing Table

1. **Add the `mapped_column`** to the appropriate model class in `models.py`:

```python
new_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

2. **Generate an Alembic migration:**
```bash
uv run alembic revision --autogenerate -m "add_new_field_to_table_name"
```

3. **Update affected repository methods** if the new column participates in queries or upsert logic. Remember: upsert methods explicitly list which fields are updated -- the new column will NOT be auto-included.

4. **Update tests** to include the new column in test fixtures and assertions.

### Add a New Repository Query

1. **Add the method** to the appropriate repository class:

```python
async def get_by_new_field(self, value: str) -> ModelClass | None:
    """Describe what this query does."""
    stmt = select(ModelClass).where(ModelClass.new_field == value)
    result = await self._session.execute(stmt)
    return result.scalar_one_or_none()
```

2. **Consider adding a database index** if the column is not already indexed:

```python
new_field: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
```

3. **Add a unit test** in `tests/unit/infra/test_repositories.py` following the existing pattern: create records via the repository, then query and assert.

### Add a New Foreign Key

1. **Add the foreign key column** in `models.py`:

```python
parent_id: Mapped[str] = mapped_column(
    String(36), ForeignKey("parent_table.id"), nullable=False
)
```

2. **Consider ON DELETE behavior.** The current models use default FK behavior (no explicit `ON DELETE` clause). For cascading deletes, add `ForeignKey("parent_table.id", ondelete="CASCADE")`.

3. **Add an integration test** that verifies the constraint by attempting an INSERT with a non-existent parent ID and asserting `IntegrityError`.

## Cross-References

- **SPEC_01 (Core Models):** Domain models that correspond to ORM models (`CandidateProfile` <-> `ProfileModel`, `Company` <-> `CompanyModel`, `NormalizedJob` <-> `NormalizedJobModel`, `ScoredJob`/`FitReport` <-> `ScoredJobModel`, `RunResult` <-> `RunHistoryModel`). Settings class defines `db_backend`, `database_url`, `postgres_url`. The `BaseRepository[T]` Protocol in `job_hunter_core.interfaces.repository` defines the expected repository interface (not currently enforced via inheritance in the concrete repos).
- **SPEC_03 (Cache):** The `CacheEntry` ORM model in `src/job_hunter_infra/cache/db_cache.py` inherits from the same `Base` declared in `models.py`, sharing the metadata registry. This means `init_db()` and `Base.metadata.create_all` will also create the `cache_entries` table. The `DBCacheClient` depends on having access to an `AsyncSession` from the same engine.

## Entity Relationship Diagram

```
profiles                    companies
+----------+               +----------+
| id (PK)  |               | id (PK)  |
| content_ |               | name     |
|   hash   |               | domain   |
| email    |               | ats_type |
| name     |               | career_  |
| ...      |               |   url    |
+----------+               | ...      |
                            +----+-----+
                                 |
                     +-----------+-----------+
                     |                       |
                jobs_raw              jobs_normalized
              +----------+          +---------------+
              | id (PK)  |          | id (PK)       |
              | company_ |          | raw_job_id    |----> jobs_raw.id (nullable)
              |   id(FK) |          | company_id(FK)|----> companies.id
              | source_  |          | content_hash  |
              |   url    |          | title         |
              | raw_html |          | jd_text       |
              | raw_json |          | embedding_json|
              | ...      |          | ...           |
              +----------+          +-------+-------+
                                            |
                                    jobs_scored
                                  +---------------+
                                  | id (PK)       |
                                  | normalized_   |
                                  |   job_id (FK) |----> jobs_normalized.id
                                  | run_id        |----> (logical ref to run_history.run_id)
                                  | score         |
                                  | fit_summary   |
                                  | ...           |
                                  +---------------+

              run_history              cache_entries
            +-------------+          +---------------+
            | id (PK)     |          | key (PK)      |
            | run_id (UQ) |          | value         |
            | status      |          | expires_at    |
            | tokens_used |          +---------------+
            | cost_usd    |
            | ...         |
            +-------------+
```

**Foreign Key Summary:**

| Child Table | Column | References | Nullable |
|-------------|--------|------------|----------|
| `jobs_raw` | `company_id` | `companies.id` | No |
| `jobs_normalized` | `raw_job_id` | `jobs_raw.id` | Yes |
| `jobs_normalized` | `company_id` | `companies.id` | No |
| `jobs_scored` | `normalized_job_id` | `jobs_normalized.id` | No |

**Note:** `jobs_scored.run_id` is a logical reference to `run_history.run_id` but is NOT a database-level foreign key. This is a deliberate design choice allowing scored jobs to be created before or independently of run history records.
