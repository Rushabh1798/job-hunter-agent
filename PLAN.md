# PLAN.md — Job Hunter Agent

## Architectural Decisions

### Decision: Monorepo over Multi-Repo
Using a monorepo with `src/` layout and four packages (`job_hunter_core`, `job_hunter_agents`, `job_hunter_infra`, `job_hunter_cli`). Rationale: the spec's pragmatic note explicitly permits this; a single git repo with clear package boundaries is faster to develop and easier to test while maintaining separation of concerns. Packages can be split later if needed.

### Decision: Async pipeline with JSON checkpoints (MVP)
Phase 1 (MVP) uses a sequential async pipeline (`Pipeline` class) with JSON checkpoint files for crash recovery. After each agent step, a checkpoint is saved to `checkpoint_dir`; on restart, the pipeline resumes from the last completed step. Temporal is planned for Phase 2 (post-MVP) to provide production-grade durability, but is not required for the MVP.

### Decision: SQLite as default DB backend
Per AD-5, the default mode is `--lite` with SQLite. PostgreSQL is optional for recurring/multi-user use and is the recommended backend for long-running or multi-user deployments.

### Decision: Local embeddings by default
Per AD-4, `sentence-transformers` with `all-MiniLM-L6-v2` (384-dim) is the default. No API key needed.

### Decision: crawl4ai as primary scraper
Per AD-7, crawl4ai handles SPA rendering, JS execution, and content extraction. Raw Playwright is a fallback only.

### Decision: Redis/DB-backed caching instead of diskcache
Persistent caching for HTML pages, company URLs, and other derived artifacts uses Redis by default, with an option to fall back to database-backed caches where Redis is unavailable. The previous `diskcache`-based implementation is removed; all cache clients must implement the `CacheClient` protocol from `job_hunter_core` and be safe under concurrent access and pipeline retries.

---

## 1. Directory and File Tree

```
job-hunter-agent/
├── CLAUDE.md                           # Persistent memory for Claude Code
├── PLAN.md                             # This file — full project plan
├── PROMPT.md                           # Original specification (read-only)
├── pyproject.toml                      # Monorepo project config
├── uv.lock                            # Lock file (auto-generated)
├── .python-version                    # Python 3.12 pin
├── .env.example                       # Documented env vars, no real values
├── .gitignore                         # Standard Python + project-specific ignores
├── .ruff.toml                         # Ruff config (if not in pyproject.toml)
├── Makefile                           # Dev commands
├── Dockerfile                         # Multi-stage build
├── docker-compose.yml                 # PostgreSQL + pgvector
├── LICENSE                            # Apache 2.0
├── README.md                          # User-facing docs
├── CONTRIBUTING.md                    # Contribution guide
├── CHANGELOG.md                       # Release notes
├── SECURITY.md                        # Vulnerability reporting
│
├── .github/
│   ├── workflows/
│   │   └── ci.yml                     # GitHub Actions CI pipeline
│   └── ISSUE_TEMPLATE/
│       ├── bug_report.md              # Bug report template
│       └── ats_support_request.md     # ATS support request template
│
├── alembic/                           # Alembic migrations (Postgres mode)
│   ├── alembic.ini                    # Alembic config
│   ├── env.py                         # Migration environment
│   └── versions/
│       └── 001_initial.py             # Initial schema + pgvector extension
│
├── src/
│   ├── job_hunter_core/               # Core domain — no external deps
│   │   ├── __init__.py
│   │   ├── constants.py               # Shared constants, enums
│   │   ├── exceptions.py              # Custom exception hierarchy
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   └── settings.py            # pydantic-settings Settings class
│   │   ├── models/
│   │   │   ├── __init__.py            # Re-exports all models
│   │   │   ├── candidate.py           # Skill, Education, CandidateProfile, SearchPreferences
│   │   │   ├── company.py             # ATSType, CareerPage, Company
│   │   │   ├── job.py                 # RawJob, NormalizedJob, FitReport, ScoredJob
│   │   │   └── run.py                 # RunConfig, AgentError, PipelineCheckpoint, RunResult
│   │   ├── interfaces/
│   │   │   ├── __init__.py
│   │   │   ├── cache.py               # CacheClient protocol
│   │   │   ├── embedder.py            # EmbedderBase protocol
│   │   │   └── repository.py          # BaseRepository protocol
│   │   └── state.py                   # PipelineState dataclass
│   │
│   ├── job_hunter_infra/              # Infrastructure — depends on core
│   │   ├── __init__.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py              # Async engine factory (Postgres/SQLite)
│   │   │   ├── models.py              # SQLAlchemy ORM table models
│   │   │   ├── session.py             # Async session factory
│   │   │   └── repositories/
│   │   │       ├── __init__.py
│   │   │       ├── profile_repo.py    # ProfileRepository
│   │   │       ├── company_repo.py    # CompanyRepository
│   │   │       ├── job_repo.py        # JobRepository (includes vector queries)
│   │   │       ├── score_repo.py      # ScoreRepository
│   │   │       └── run_repo.py        # RunRepository
│   │   ├── cache/
│   │   │   ├── __init__.py
│   │   │   ├── redis_cache.py         # RedisCacheClient implementation
│   │   │   ├── db_cache.py            # DBCacheClient implementation (fallback)
│   │   │   ├── page_cache.py          # PageCache (HTML content)
│   │   │   └── company_cache.py       # CompanyURLCache (career URLs)
│   │   └── vector/
│   │       ├── __init__.py
│   │       └── similarity.py          # Brute-force cosine similarity for SQLite mode
│   │
│   ├── job_hunter_agents/             # Agents — depends on core + infra
│   │   ├── __init__.py
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                # BaseAgent ABC
│   │   │   ├── resume_parser.py       # ResumeParserAgent
│   │   │   ├── prefs_parser.py        # PrefsParserAgent
│   │   │   ├── company_finder.py      # CompanyFinderAgent (LangGraph internal)
│   │   │   ├── jobs_scraper.py        # JobsScraperAgent
│   │   │   ├── job_processor.py       # JobProcessorAgent
│   │   │   ├── jobs_scorer.py         # JobsScorerAgent (LangGraph internal)
│   │   │   ├── aggregator.py          # AggregatorAgent
│   │   │   └── notifier.py            # NotifierAgent
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── pdf_parser.py          # PDFParser (docling -> pdfplumber -> pypdf fallback)
│   │   │   ├── web_search.py          # WebSearchTool (Tavily)
│   │   │   ├── browser.py             # WebScraper (crawl4ai -> Playwright fallback)
│   │   │   ├── embedder.py            # LocalEmbedder, VoyageEmbedder
│   │   │   ├── email_sender.py        # EmailSender (SendGrid / SMTP)
│   │   │   └── ats_clients/
│   │   │       ├── __init__.py
│   │   │       ├── base.py            # BaseATSClient ABC
│   │   │       ├── greenhouse.py      # GreenhouseClient
│   │   │       ├── lever.py           # LeverClient
│   │   │       ├── ashby.py           # AshbyClient
│   │   │       └── workday.py         # WorkdayClient (crawl4ai-based)
│   │   ├── prompts/
│   │   │   ├── __init__.py
│   │   │   ├── resume_parser.py       # Resume parsing prompt (v1)
│   │   │   ├── prefs_parser.py        # Preferences parsing prompt (v1)
│   │   │   ├── company_finder.py      # Company discovery prompt (v1)
│   │   │   ├── job_processor.py       # Job normalization prompt (v1)
│   │   │   └── job_scorer.py          # Job scoring prompt (v1)
│   │   ├── orchestrator/
│   │   │   ├── __init__.py
│   │   │   ├── pipeline.py            # Pipeline class with checkpoint/resume
│   │   │   └── checkpoint.py          # Checkpoint serialization/deserialization
│   │   └── observability/             # TODO: Phase 6
│   │       ├── __init__.py
│   │       ├── logging.py             # structlog configuration (TODO)
│   │       ├── tracing.py             # LangSmith tracing (TODO)
│   │       └── cost_tracker.py        # Per-run cost accumulator + guardrail (TODO)
│   │
│   └── job_hunter_cli/                # CLI — depends on all packages
│       ├── __init__.py
│       └── main.py                    # typer CLI app with commands
│
├── tests/
│   ├── conftest.py                    # Shared fixtures
│   ├── unit/
│   │   ├── conftest.py               # Unit test fixtures (mocks)
│   │   ├── core/
│   │   │   ├── test_settings.py       # Settings validation tests
│   │   │   ├── test_candidate.py      # CandidateProfile model tests
│   │   │   ├── test_company.py        # Company model tests
│   │   │   ├── test_job.py            # Job model tests
│   │   │   └── test_run.py            # Run model tests
│   │   ├── agents/
│   │   │   ├── test_resume_parser.py  # Resume parser tests
│   │   │   ├── test_prefs_parser.py   # Prefs parser tests
│   │   │   ├── test_company_finder.py # Company finder tests
│   │   │   ├── test_jobs_scraper.py   # Scraper tests
│   │   │   ├── test_job_processor.py  # Processor tests
│   │   │   ├── test_jobs_scorer.py    # Scorer tests
│   │   │   ├── test_aggregator.py     # Aggregator tests
│   │   │   └── test_notifier.py       # Notifier tests
│   │   ├── tools/
│   │   │   ├── test_pdf_parser.py     # PDF parser tests
│   │   │   ├── test_web_search.py     # Web search tests
│   │   │   ├── test_browser.py        # Browser/scraper tests
│   │   │   ├── test_embedder.py       # Embedder tests
│   │   │   ├── test_email_sender.py   # Email sender tests
│   │   │   └── test_ats_clients.py    # ATS client tests
│   │   └── infra/
│   │       ├── test_cache_backends.py # Redis + DB cache tests
│   │       ├── test_similarity.py     # Vector similarity tests
│   │       └── test_repositories.py   # Repository tests (SQLite)
│   ├── integration/
│   │   ├── conftest.py               # Integration fixtures (real SQLite/Postgres)
│   │   ├── test_pipeline.py           # Full pipeline integration test
│   │   └── test_db_lifecycle.py       # DB CRUD lifecycle tests
│   ├── e2e/
│   │   └── test_full_pipeline.py      # End-to-end pipeline test (--dry-run)
│   └── fixtures/
│       ├── sample_resume.pdf          # Test resume PDF
│       ├── sample_greenhouse.json     # Greenhouse API response
│       ├── sample_lever.json          # Lever API response
│       ├── sample_career_page.html    # Career page HTML
│       └── sample_jd.html            # Job description HTML
│
└── output/                            # Runtime output (gitignored)
```

---

## 2. Dependency Graph Between Modules

```
job_hunter_core (no internal deps)
  ├── models/candidate.py     ← uses pydantic
  ├── models/company.py       ← uses pydantic
  ├── models/job.py           ← uses pydantic
  ├── models/run.py           ← uses pydantic
  ├── config/settings.py      ← uses pydantic-settings
  ├── interfaces/cache.py     ← Protocol (typing)
  ├── interfaces/embedder.py  ← Protocol (typing)
  ├── interfaces/repository.py ← Protocol (typing)
  ├── state.py                ← imports models/*
  ├── constants.py            ← no imports
  └── exceptions.py           ← no imports

job_hunter_infra (depends on core)
  ├── db/engine.py            ← sqlalchemy, core.config
  ├── db/models.py            ← sqlalchemy, core.models
  ├── db/session.py           ← sqlalchemy, db.engine
  ├── db/repositories/*.py    ← sqlalchemy, db.models, core.models
  ├── cache/redis_cache.py    ← redis/aioredis, core.interfaces.cache
  ├── cache/db_cache.py       ← sqlalchemy, core.interfaces.cache
  ├── cache/page_cache.py     ← cache.redis_cache or cache.db_cache
  ├── cache/company_cache.py  ← cache.redis_cache or cache.db_cache
  └── vector/similarity.py    ← numpy

job_hunter_agents (depends on core + infra)
  ├── agents/base.py          ← core.config, core.state, core.exceptions, anthropic, instructor
  ├── agents/resume_parser.py ← agents.base, tools.pdf_parser, prompts.resume_parser, infra.cache
  ├── agents/prefs_parser.py  ← agents.base, prompts.prefs_parser
  ├── agents/company_finder.py ← agents.base, tools.web_search, tools.browser, tools.ats_clients, infra.cache, langgraph
  ├── agents/jobs_scraper.py  ← agents.base, tools.browser, tools.ats_clients, infra.cache
  ├── agents/job_processor.py ← agents.base, tools.embedder, infra.db.repositories
  ├── agents/jobs_scorer.py   ← agents.base, tools.embedder, infra.db.repositories, infra.vector, langgraph
  ├── agents/aggregator.py    ← agents.base, pandas, openpyxl
  ├── agents/notifier.py      ← agents.base, tools.email_sender, jinja2
  ├── tools/pdf_parser.py     ← docling, pdfplumber
  ├── tools/web_search.py     ← tavily-python
  ├── tools/browser.py        ← crawl4ai, playwright
  ├── tools/embedder.py       ← sentence-transformers, core.interfaces.embedder
  ├── tools/email_sender.py   ← sendgrid, aiosmtplib
  ├── tools/ats_clients/*.py  ← httpx, tools.browser
  ├── prompts/*.py            ← no imports (string templates)
  ├── orchestrator/pipeline.py ← agents.*, core.state, core.config
  ├── orchestrator/checkpoint.py ← core.models.run
  └── observability/*.py      ← structlog, langsmith

job_hunter_cli (depends on all)
  └── main.py                 ← typer, rich, core.config, orchestrator.pipeline
```

**No circular imports**: core -> infra -> agents -> cli (strict one-way dependency).

---

## 3. Database Schema

### Table: profiles
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default uuid4 |
| content_hash | VARCHAR(64) | UNIQUE, NOT NULL |
| email | VARCHAR(255) | NOT NULL |
| name | VARCHAR(255) | NOT NULL |
| phone | VARCHAR(50) | |
| location | VARCHAR(255) | |
| current_title | VARCHAR(255) | |
| years_of_experience | FLOAT | NOT NULL |
| seniority_level | VARCHAR(50) | |
| skills_json | JSON | NOT NULL |
| education_json | JSON | |
| past_titles_json | JSON | |
| industries_json | JSON | |
| tech_stack_json | JSON | |
| raw_text | TEXT | NOT NULL |
| created_at | TIMESTAMP | NOT NULL, server default |
| updated_at | TIMESTAMP | NOT NULL, server default, on update |

### Table: companies
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default uuid4 |
| name | VARCHAR(255) | NOT NULL |
| domain | VARCHAR(255) | NOT NULL, INDEX |
| ats_type | VARCHAR(50) | NOT NULL, default 'unknown' |
| career_url | VARCHAR(1024) | NOT NULL |
| api_endpoint | VARCHAR(1024) | |
| industry | VARCHAR(255) | |
| size | VARCHAR(50) | |
| org_type | VARCHAR(100) | |
| description | TEXT | |
| source_confidence | FLOAT | default 1.0 |
| scrape_strategy | VARCHAR(50) | default 'crawl4ai' |
| last_scraped_at | TIMESTAMP | |
| created_at | TIMESTAMP | NOT NULL, server default |
| updated_at | TIMESTAMP | NOT NULL, server default |

### Table: jobs_raw
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default uuid4 |
| company_id | UUID | FK -> companies.id, NOT NULL |
| source_url | VARCHAR(2048) | NOT NULL |
| raw_html | TEXT | |
| raw_json | JSON | |
| scrape_strategy | VARCHAR(50) | NOT NULL |
| source_confidence | FLOAT | default 1.0 |
| scraped_at | TIMESTAMP | NOT NULL, server default |
| created_at | TIMESTAMP | NOT NULL, server default |

### Table: jobs_normalized
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default uuid4 |
| raw_job_id | UUID | FK -> jobs_raw.id |
| company_id | UUID | FK -> companies.id, NOT NULL |
| company_name | VARCHAR(255) | NOT NULL |
| title | VARCHAR(500) | NOT NULL |
| jd_text | TEXT | NOT NULL |
| apply_url | VARCHAR(2048) | NOT NULL |
| location | VARCHAR(255) | |
| remote_type | VARCHAR(50) | default 'unknown' |
| posted_date | DATE | |
| salary_min | INTEGER | |
| salary_max | INTEGER | |
| currency | VARCHAR(10) | |
| required_skills_json | JSON | |
| preferred_skills_json | JSON | |
| required_experience_years | FLOAT | |
| seniority_level | VARCHAR(50) | |
| department | VARCHAR(255) | |
| content_hash | VARCHAR(64) | UNIQUE, NOT NULL, INDEX |
| embedding | Vector(384) | Postgres: pgvector; SQLite: JSON text |
| processed_at | TIMESTAMP | NOT NULL, server default |
| created_at | TIMESTAMP | NOT NULL, server default |
| updated_at | TIMESTAMP | NOT NULL, server default |

**pgvector index** (Postgres only):
```sql
CREATE INDEX idx_jobs_embedding ON jobs_normalized
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

### Table: jobs_scored
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default uuid4 |
| normalized_job_id | UUID | FK -> jobs_normalized.id, NOT NULL |
| run_id | VARCHAR(100) | NOT NULL, INDEX |
| score | INTEGER | NOT NULL |
| skill_overlap_json | JSON | |
| skill_gaps_json | JSON | |
| seniority_match | BOOLEAN | |
| location_match | BOOLEAN | |
| org_type_match | BOOLEAN | |
| fit_summary | TEXT | |
| recommendation | VARCHAR(50) | |
| confidence | FLOAT | |
| rank | INTEGER | |
| scored_at | TIMESTAMP | NOT NULL, server default |
| created_at | TIMESTAMP | NOT NULL, server default |

### Table: run_history
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default uuid4 |
| run_id | VARCHAR(100) | UNIQUE, NOT NULL, INDEX |
| status | VARCHAR(50) | NOT NULL |
| companies_attempted | INTEGER | default 0 |
| companies_succeeded | INTEGER | default 0 |
| jobs_scraped | INTEGER | default 0 |
| jobs_scored | INTEGER | default 0 |
| jobs_in_output | INTEGER | default 0 |
| output_files_json | JSON | |
| email_sent | BOOLEAN | default false |
| tokens_used | INTEGER | default 0 |
| cost_usd | FLOAT | default 0.0 |
| duration_seconds | FLOAT | |
| errors_json | JSON | |
| created_at | TIMESTAMP | NOT NULL, server default |

### Migrations
- **Alembic** for PostgreSQL: initial migration creates all tables + `CREATE EXTENSION IF NOT EXISTS vector`
- **SQLite**: tables created inline via SQLAlchemy `metadata.create_all()` (no Alembic needed)
- Embedding column in SQLite stored as TEXT (JSON-serialized list of floats)

---

## 4. Pipeline Execution Graph (Sequential Async Pipeline with Checkpoints)

```
START (Pipeline.run)
  │
  ▼
[1. parse_resume] ─────── ResumeParserAgent.run → checkpoint saved
  │                         State: config + profile
  ▼
[2. parse_prefs] ──────── PrefsParserAgent.run → checkpoint saved
  │                         State: + preferences
  ▼
[3. find_companies] ───── CompanyFinderAgent.run → checkpoint saved
  │                         State: + companies[]
  │                         Error route: 0 companies → fatal, stop
  ▼
[4. scrape_jobs] ─────── JobsScraperAgent.run → checkpoint saved
  │                         State: + raw_jobs[]
  │                         Error route: per-company errors logged, continue
  ▼
[5. process_jobs] ─────── JobProcessorAgent.run → checkpoint saved
  │                         State: + normalized_jobs[] (with embeddings)
  │                         Error route: per-job errors logged, continue
  ▼
[6. score_jobs] ──────── JobsScorerAgent.run → checkpoint saved
  │                         State: + scored_jobs[]
  │                         Error route: 0 above threshold → empty report
  ▼
[7. aggregate] ──────── AggregatorAgent.run → checkpoint saved
  │                         State: + output files written
  ▼
[8. notify] ─────────── NotifierAgent.run → checkpoint saved
  │                         State: + email_sent flag
  ▼
END → RunResult (summarized from PipelineState)
```

**Error routes**:
- Any step: `CostLimitExceededError` → checkpoint + stop with status="partial"
- Any step: `FatalAgentError` → checkpoint + stop with status="failed"
- Non-fatal errors: logged to `state.errors[]`, pipeline continues
- Per-agent timeout: `asyncio.wait_for` with configurable `agent_timeout_seconds`

**Resume from checkpoint**: On startup, check `checkpoint_dir` for `{run_id}--*.json` files. Load the latest completed step's checkpoint and skip completed steps.

---

## 5. LangGraph Usage

### CompanyFinderAgent (Internal LangGraph)
```
StateGraph nodes:
  generate_candidates → validate_career_pages → detect_ats → filter_and_rank

State (TypedDict):
  candidates: list[dict]         # LLM-generated company candidates
  validated: list[Company]       # Companies with confirmed career pages
  filtered: list[Company]        # Companies passing all filters
  errors: list[str]              # Validation errors
```

### JobsScorerAgent (Internal LangGraph)
```
StateGraph nodes:
  semantic_prefilter → llm_rerank_batch → calibrate_scores → sort_and_filter

State (TypedDict):
  shortlist: list[NormalizedJob]  # After semantic prefilter
  scored: list[ScoredJob]         # After LLM reranking
  calibrated: list[ScoredJob]     # After score calibration
  final: list[ScoredJob]          # After threshold filter + sort
```

### All other agents: simple async functions, no LangGraph.

---

## 6. Pydantic Model Inventory

### job_hunter_core.models.candidate
| Model | Fields | Key Validators |
|-------|--------|----------------|
| Skill | name, level?, years? | level must be valid Literal if provided |
| Education | degree?, field?, institution?, graduation_year? | graduation_year 1950-2030 if provided |
| CandidateProfile | name, email, phone?, location?, linkedin_url?, github_url?, current_title?, years_of_experience, skills, past_titles, industries, education, seniority_level?, tech_stack, raw_text, parsed_at, content_hash | email is EmailStr; years_of_experience >= 0; content_hash is sha256 |
| SearchPreferences | preferred_locations, remote_preference, target_titles, target_seniority, excluded_titles, org_types, company_sizes, preferred_industries, excluded_companies, preferred_companies, min_salary?, max_salary?, currency, raw_text | min_salary <= max_salary if both set |

### job_hunter_core.models.company
| Model | Fields | Key Validators |
|-------|--------|----------------|
| ATSType | enum: greenhouse, lever, workday, ashby, icims, taleo, custom, unknown | str enum |
| CareerPage | url, ats_type, api_endpoint?, last_scraped_at?, scrape_strategy | url is HttpUrl |
| Company | id, name, domain, career_page, industry?, size?, org_type?, description?, source_confidence | source_confidence 0.0-1.0 |

### job_hunter_core.models.job
| Model | Fields | Key Validators |
|-------|--------|----------------|
| RawJob | id, company_id, company_name, raw_html?, raw_json?, source_url, scraped_at, scrape_strategy, source_confidence | source_confidence 0.0-1.0 |
| NormalizedJob | id, raw_job_id, company_id, company_name, title, jd_text, apply_url, location?, remote_type, posted_date?, salary_min?, salary_max?, currency?, required_skills, preferred_skills, required_experience_years?, seniority_level?, department?, content_hash, processed_at, embedding? | content_hash is sha256; salary_min <= salary_max |
| FitReport | score, skill_overlap, skill_gaps, seniority_match, location_match, org_type_match, summary, recommendation, confidence | score 0-100; confidence 0.0-1.0 |
| ScoredJob | job, fit_report, rank?, scored_at | rank >= 1 if set |

### job_hunter_core.models.run
| Model | Fields | Key Validators |
|-------|--------|----------------|
| RunConfig | run_id, resume_path, preferences_text, dry_run, force_rescrape, company_limit?, output_formats, lite_mode | resume_path must exist |
| AgentError | agent_name, error_type, error_message, company_name?, job_id?, timestamp, is_fatal | |
| PipelineCheckpoint | run_id, completed_step, state_snapshot, saved_at | |
| RunResult | run_id, status, companies_attempted, companies_succeeded, jobs_scraped, jobs_scored, jobs_in_output, output_files, email_sent, errors, total_tokens_used, estimated_cost_usd, duration_seconds, completed_at | status is Literal |

---

## 7. External API Surface

| Service | Library | Calls | Auth | Rate Limit |
|---------|---------|-------|------|------------|
| Anthropic (Claude Haiku) | anthropic + instructor | Resume parsing, job processing, preferences parsing | API key (JH_ANTHROPIC_API_KEY) | Handled by tenacity retry |
| Anthropic (Claude Sonnet) | anthropic + instructor | Company generation, job scoring | API key | Handled by tenacity retry |
| Tavily | tavily-python | Web search for career pages, job search | API key (JH_TAVILY_API_KEY) | Max 5 concurrent |
| crawl4ai | crawl4ai | Career page scraping, job page scraping | None | Max 5 concurrent, 3 req/min per domain |
| Playwright | playwright | Fallback scraping for crawl4ai failures | None | Max 5 concurrent |
| Greenhouse API | httpx | Job listings for Greenhouse-powered career pages | None (public API) | Respect rate headers |
| Lever API | httpx | Job listings for Lever-powered career pages | None (public API) | Respect rate headers |
| Ashby API | httpx | Job listings for Ashby-powered career pages | None (public API) | Respect rate headers |
| SendGrid | sendgrid | Email delivery | API key (JH_SENDGRID_API_KEY) | N/A |
| SMTP | aiosmtplib | Email delivery (alternative) | User/password | N/A |
| Voyage AI | voyageai | Text embeddings (optional) | API key (JH_VOYAGE_API_KEY) | Handled by tenacity retry |
| sentence-transformers | sentence-transformers | Text embeddings (local, default) | None | N/A (local) |
| LangSmith | langsmith | Tracing (optional) | API key (JH_LANGSMITH_API_KEY) | N/A |

---

## 8. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| 1 | Career page scraping fails (JS-heavy SPAs, anti-bot) | High | High | crawl4ai handles most SPAs; Playwright fallback; ATS API detection bypasses scraping entirely; per-company error isolation |
| 2 | LLM returns malformed structured output | Medium | Medium | instructor library handles retries + validation; max 3 retries per call; fallback to raw text parsing |
| 3 | Unexpected LLM cost overrun | Medium | High | Hard cost guardrail ($5 default); per-call cost tracking; checkpoint before expensive steps |
| 4 | Career page URL detection fails (company not found) | Medium | Medium | Multi-strategy: ATS API check → Tavily search → common path crawl; cache successful URLs; log failures |
| 5 | Rate limiting by career sites | Medium | Medium | Per-domain semaphore (3 req/min); asyncio.Semaphore for concurrency; tenacity exponential backoff |
| 6 | PDF parsing fails (scanned, encrypted, image-only) | Low | Medium | docling → pdfplumber → pypdf fallback chain; clear error messages for unsupported formats |
| 7 | Pipeline crash mid-run loses progress | Medium | High | JSON checkpoint files with per-step serialization; pipeline resumes from last completed step; DB-backed state for large artifacts; idempotent operations via content_hash |
| 8 | Database schema mismatch between Postgres and SQLite | Low | Medium | Single SQLAlchemy model set; vector column handled conditionally (pgvector vs JSON text) |
| 9 | Duplicate jobs in output | Medium | Low | content_hash deduplication at DB level (UNIQUE constraint); check before insert |
| 10 | Email delivery failure | Low | Low | Non-fatal error; files always written locally; email_sent=False in RunResult |

---

## 9. Implementation Order

| Order | Phase | What | Status |
|-------|-------|------|--------|
| 1 | Phase 0 | CLAUDE.md + PLAN.md | DONE |
| 2 | Phase 1 | Project scaffold + pyproject.toml | DONE |
| 3 | Phase 2 | Core models + settings | DONE |
| 4 | Phase 3 | Infrastructure (DB, cache, embedder) | DONE |
| 5 | Phase 4 | Tools (PDF, ATS, browser, search) | DONE |
| 6 | Phase 5 | All 8 agents + pipeline + CLI | DONE (includes former Phase 6) |
| 7 | Phase 6 | Observability (logging, tracing, cost tracking) | TODO |
| 8 | Phase 7 | Testing + self-improvement (80% coverage) | TODO |
| 9 | Phase 8 | Docker + local dev | TODO |
| 10 | Phase 9 | GitHub open source standards (README, CI) | TODO |

---

## 10. Workflow Durability and Resume Strategy (Checkpoints)

The MVP pipeline uses JSON checkpoint files for crash recovery. After each agent step completes, a `PipelineCheckpoint` is serialized to `{checkpoint_dir}/{run_id}--{step}.json`. On restart, the pipeline loads the latest checkpoint and skips completed steps.

**Durable state**:
- `RunConfig` payload (including `run_id`) is the canonical identifier for a run.
- Agents read/write to the DB (`profiles`, `companies`, `jobs_raw`, `jobs_normalized`, `jobs_scored`, `run_history`) using idempotent operations (e.g., checking `content_hash` or `run_id` before insert).
- Checkpoint files store serialized `PipelineState` snapshots so the pipeline can resume from the last successful step.

**Resume logic**:
1. A `run_id` uniquely identifies a pipeline execution and its checkpoint files.
2. On startup, `load_latest_checkpoint(run_id, checkpoint_dir)` globs `{run_id}--*.json`, selects the most recent by mtime, and deserializes it into a `PipelineCheckpoint`.
3. `PipelineState.from_checkpoint()` reconstructs state; `completed_steps` set causes the pipeline loop to skip already-finished steps.
4. DB operations are idempotent via `content_hash` UNIQUE constraints, so replaying a step does not create duplicates.

**RunResult mapping**:
- When the pipeline completes, `PipelineState.build_result()` constructs a `RunResult` with aggregates (companies_attempted, jobs_scored, output_files, cost_usd, duration_seconds).
- This `RunResult` is what the CLI displays and what tests assert against.

**Future**: Temporal orchestration (Phase 2) will replace checkpoint files with durable workflow history and activity-level retries for production deployments.

---

## 11. Plan Validation Checklist

- [x] Every agent has a corresponding Python class (8 agents → 8 classes in agents/)
- [x] Every external API call has a corresponding mock in the test plan (see tests/unit/tools/)
- [x] Every database table has a corresponding migration (Alembic for Postgres, create_all for SQLite)
- [x] pgvector extension is created in the initial migration (001_initial.py)
- [x] Every Pydantic model has validators for its most likely failure modes (documented in model inventory)
- [x] The pipeline checkpoint schema covers all data between steps (PipelineCheckpoint.state_snapshot)
- [x] There are no circular imports in the dependency graph (core → infra → agents → cli)
- [x] The retry strategy is defined for every agent that makes network calls (tenacity in BaseAgent)
- [x] The system works end-to-end with `--lite` flag (SQLite, local embeddings, no Docker)
- [x] Each package can be tested independently (separate test directories, core has no external deps)

---

## 12. End-to-End Testing Suite

The project includes both a user-guided CLI command and a pytest-based E2E test to validate the full pipeline.

### 12.1 CLI E2E Command

- **Command**: `job-hunter e2e-test`
- **Behavior**:
  - Validates that all required environment variables and configuration fields are set (Anthropic, Tavily, DB, email provider, etc.).
  - Prints clear guidance for any missing or inconsistent configuration and exits with a non-zero status if critical settings are absent.
  - Offers a “safe-cost” mode that:
    - Enforces a small `company_limit` (for example, 3–5 companies).
    - Tightens the `max_cost_per_run_usd` guardrail.
  - Runs the `Pipeline` directly with either:
    - A sample resume/preferences pair from `tests/fixtures/`, or
    - User-specified resume and preferences arguments.
  - On completion, prints a summary including:
    - Run status and `run_id`.
    - Companies attempted/succeeded, jobs scraped/scored.
    - Output files written and their paths.
    - Whether an email was sent.

### 12.2 Pytest E2E Test

- **File**: `tests/e2e/test_full_pipeline.py`
- **Markers and gating**:
  - Uses a custom marker (`@pytest.mark.e2e`) and is skipped by default unless `E2E_ENABLED=1` is set in the environment.
  - Fails fast with a helpful message if critical environment variables or services (DB, API keys) are not available.
- **Behavior**:
  - Instantiates the `Pipeline` class with test `Settings` and `RunConfig`.
  - Runs `pipeline.run(config)` with test fixtures (resume PDF + preferences text) using `--dry-run`.
  - Asserts:
    - A new `run_history` row exists with `status=”success”` for the test `run_id`.
    - The `profiles`, `companies`, `jobs_normalized`, and `jobs_scored` tables have records associated with the `run_id`.
    - At least one output file was generated in the configured `output_dir`.
    - No fatal errors were recorded in the `errors` field of the `RunResult`.

### 12.3 Environment and Configuration Requirements for E2E

- **Database**:
  - `JH_DB_BACKEND` and `JH_DATABASE_URL` (or `JH_POSTGRES_URL` when using Postgres) must be set and reachable. SQLite works for basic E2E.
- **Cache**:
  - `JH_REDIS_URL` for Redis-backed caching, or `JH_CACHE_BACKEND=db` for DB-backed fallback.
- **LLM & Search**:
  - `JH_ANTHROPIC_API_KEY` and `JH_TAVILY_API_KEY`.
- **Email**:
  - Either `JH_SENDGRID_API_KEY` (for SendGrid) or SMTP credentials (`JH_SMTP_HOST`, `JH_SMTP_PORT`, `JH_SMTP_USER`, `JH_SMTP_PASSWORD`) depending on `email_provider`.
- **Optional**:
  - `JH_VOYAGE_API_KEY` for Voyage embeddings.
  - `JH_LANGSMITH_API_KEY` for tracing.

Settings validation in `tests/unit/core/test_settings.py` is extended to ensure that:
- Required fields for the selected providers (e.g., Redis, Voyage, SendGrid) are present.
- E2E tests clearly indicate which configuration is missing rather than failing with generic errors.
