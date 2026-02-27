# CLAUDE.md — job-hunter-agent

## What This Repo Does
Monorepo for an autonomous multi-agent job discovery system. Accepts a resume PDF and freeform job preferences, discovers target companies, scrapes their official career pages, scores jobs against the candidate's profile using LLM reasoning, and outputs a ranked CSV/Excel with scores, fit reports, and apply URLs. Optionally emails results to the candidate.

## Architecture
- **Monorepo** with four packages under `src/`: `job_hunter_core`, `job_hunter_agents`, `job_hunter_infra`, `job_hunter_cli`
- **AD-1**: PostgreSQL + pgvector for relational + vector storage (no standalone vector DB)
- **AD-2**: Dual orchestration: checkpoint-based pipeline (default) or Temporal workflows (`--temporal`); no silent fallback — `TemporalConnectionError` raised if Temporal unavailable
- **AD-3**: Redis for persistent caching (default), DB-backed cache fallback for `--lite` mode. diskcache removed.
- **AD-4**: Local sentence-transformers embeddings by default; Voyage API optional
- **AD-5**: `--lite` mode uses SQLite + local embeddings, zero Docker dependencies
- **AD-6**: llm-gateway for provider-agnostic LLM abstraction (replaces direct anthropic + instructor usage)
- **AD-7**: crawl4ai for career page scraping (Playwright under the hood)
- **AD-8**: Docker image ~3-4GB (PyTorch + Chromium); CPU-only torch wheels deferred
- **AD-9**: Vendor-agnostic tool abstractions — `SearchProvider` and `PageScraper` Protocols with factory functions; agents use factories, not concrete classes
- **AD-10**: DuckDuckGo search (free, no API key) for integration tests; Tavily for production
- **AD-11**: Two-tier test mocking — `activate_dry_run_patches()` (full mock) vs `activate_integration_patches()` (LLM + email + PDF only)
- **AD-12**: Run report generation from OTEL spans — shows component status (MOCK/REAL), agent timing, flow linkage
- **6 layers**: Entry/CLI -> Orchestrator -> Parsing -> Company Discovery -> Scraping -> Matching/Output
- LangGraph used only inside CompanyFinderAgent and JobsScorerAgent for multi-step LLM reasoning
- Top-level pipeline is a simple async sequential pipeline, NOT LangGraph
- Temporal workflow available for durable execution with per-company parallel scraping

## Build & Run
```bash
# Native (local Python)
make install                             # uv sync + playwright
make test                                # unit tests
make lint                                # ruff + mypy
make run ARGS='resume.pdf --prefs "..."' # run with postgres + redis
make run-trace ARGS='resume.pdf --prefs "..."' # run with OTLP tracing (Jaeger)
make run-lite ARGS='resume.pdf --prefs "..." --dry-run'  # SQLite, no Docker
make run-temporal ARGS='resume.pdf --prefs "..."'  # run via Temporal workflow
make worker QUEUE=default                # start Temporal worker

# Docker
make dev                                 # start postgres + redis
make dev-trace                           # start postgres + redis + Jaeger
make dev-temporal                        # start postgres + redis + Temporal + UI
make dev-down                            # stop infra
make docker-build                        # build image
make docker-run ARGS='--prefs "..."'     # run in full Docker (resume in data/)
make docker-run-lite ARGS='--prefs "..."' # run lite in Docker
```

## Key Files
- `src/job_hunter_core/models/` — All Pydantic domain models
- `src/job_hunter_core/config/settings.py` — pydantic-settings configuration
- `src/job_hunter_agents/agents/` — All 8 agent implementations
- `src/job_hunter_agents/orchestrator/pipeline.py` — Sequential async pipeline with checkpoints
- `src/job_hunter_agents/prompts/` — Versioned LLM prompt templates
- `src/job_hunter_agents/tools/` — PDF parser, ATS clients, scraper, search (Tavily + DuckDuckGo), embedder, factories
- `src/job_hunter_agents/observability/run_report.py` — Run report generation from OTEL spans
- `src/job_hunter_core/interfaces/search.py` — SearchProvider Protocol
- `src/job_hunter_core/interfaces/scraper.py` — PageScraper Protocol
- `src/job_hunter_infra/db/` — SQLAlchemy ORM, repositories, migrations
- `src/job_hunter_infra/cache/` — Redis + DB-backed cache implementations
- `src/job_hunter_agents/orchestrator/checkpoint.py` — Checkpoint serialization/deserialization
- `src/job_hunter_agents/orchestrator/temporal_workflow.py` — Temporal workflow definition
- `src/job_hunter_agents/orchestrator/temporal_activities.py` — Temporal activity wrappers
- `src/job_hunter_agents/orchestrator/temporal_orchestrator.py` — Temporal orchestrator with fallback
- `src/job_hunter_agents/orchestrator/temporal_client.py` — Temporal client factory (mTLS, API key)
- `src/job_hunter_cli/main.py` — typer CLI entrypoint

## Dependencies
- **LLM**: llm-gateway (provider-agnostic: Anthropic, local_claude, fake) — wraps anthropic + instructor internally
- **Search**: Tavily API (production) or DuckDuckGo (free, integration tests) via `SearchProvider` Protocol
- **Scraping**: crawl4ai + Playwright
- **PDF**: docling (primary), pdfplumber (fallback)
- **Database**: SQLAlchemy async, asyncpg (Postgres), aiosqlite (SQLite)
- **Vector**: pgvector (Postgres mode), NumPy brute-force (SQLite mode)
- **Embeddings**: sentence-transformers (local), Voyage API (optional)
- **Cache**: redis (default), DB-backed (fallback for --lite)
- **Email**: SendGrid or SMTP via aiosmtplib
- **CLI**: typer + rich
- **Orchestration**: Temporal (optional, for durable workflows)
- **Observability**: structlog, OpenTelemetry (Jaeger), LangSmith (optional), tenacity

## Conventions
- Python 3.12+, strict mypy, Ruff linting
- All functions have type annotations and docstrings
- No function body > 50 lines, no file > 300 lines
- No `print()` — use structlog
- No bare `except:` — catch specific exceptions
- `datetime.now(UTC)` not `datetime.utcnow()`
- Agents are stateless; all state in PipelineState
- Agents don't import other agents; communicate via PipelineState
- Tools have no knowledge of agents
- DB repositories contain zero business logic
- Conventional Commits: `feat:`, `fix:`, `test:`, `refactor:`, `docs:`
- Test files mirror source: `agents/scorer.py` -> `tests/unit/agents/test_scorer.py`

## Spec Files (Context Switching)
Detailed component specs live in `docs/specs/`. Load only the spec(s) you need for the current task instead of reading source code. See `docs/SPEC_INDEX.md` for the task-to-spec mapping.

| Spec | Scope |
|------|-------|
| SPEC_01 | Core models, config, interfaces, state, constants, exceptions |
| SPEC_02 | ORM models, engine/session, 5 repositories |
| SPEC_03 | Redis + DB cache, company/page caches, vector similarity |
| SPEC_04 | BaseAgent, Pipeline, checkpoint, dryrun |
| SPEC_05 | ResumeParser + PrefsParser agents + prompts |
| SPEC_06 | CompanyFinder + JobsScraper agents + prompts |
| SPEC_07 | PDF parser, web scraper, web search, embedder, email sender |
| SPEC_08 | ATS clients (Greenhouse, Lever, Ashby, Workday) |
| SPEC_09 | JobProcessor + JobsScorer + Aggregator + Notifier + prompts |
| SPEC_10 | Logging, tracing, cost tracking |
| SPEC_11 | CLI, Makefile, Docker, CI, test mocks/fixtures |

## Known Issues / TODOs
- Phases 0-14 complete; Phase 15 (adaptive pipeline quality) in progress
- **Active work**: Achieving GOAL.md criteria (10+ unique company jobs, location-relevant, posted dates, specific apply URLs). See `GOAL.md` and `scripts/verify_goal.py`.
- Pipeline run configuration: `run_live_pipeline.py` (local_claude, SQLite, DuckDuckGo, adaptive mode)
- Terraform IaC and Kubernetes manifests deferred to future
- Web UI deferred to future

## Inter-Repo Dependencies
This is a monorepo. Internal dependency order:
- `job_hunter_core` — no internal deps (models, interfaces, config)
- `job_hunter_infra` — depends on `job_hunter_core`
- `job_hunter_agents` — depends on `job_hunter_core`, `job_hunter_infra`
- `job_hunter_cli` — depends on all three above

## Testing
```bash
uv run pytest -m unit          # fast, fully mocked
uv run pytest -m integration   # requires Postgres + Redis (make dev)
uv run pytest -m live          # requires real API keys in .env
uv run pytest                  # all tests
make test-int                  # start infra + run integration tests
make test-e2e                  # run e2e + live tests
make test-live                 # run live tests only
```
- Unit tests: LLM calls use FakeLLMProvider (via `llm_provider="fake"` in settings), HTTP mocked in-process
- Integration tests: two modes — dry-run patches (full mock) and integration patches (LLM/email/PDF only, real search/scraping/ATS/DB/cache)
- Run reports: OTEL-based test reports showing component status (MOCK/REAL), agent timing, flow linkage
- Live E2E tests: real APIs, company_limit=1, cost guardrail < $2.00
- Fixtures: `tests/fixtures/` has sample PDF, LLM response JSONs, ATS responses, HTML
- Fakes: `tests/mocks/mock_tools.py` (named tool fakes), `tests/mocks/mock_llm.py` (LLM dispatcher)
- Coverage target: 90% (enforced in pre-commit hook, CI, and pyproject.toml)
- Pre-commit hook mirrors CI: ruff check + ruff format + mypy + unit tests (90% coverage gate)

## Recent Changes
- Phase 15 (in progress): Adaptive pipeline quality — `AdaptivePipeline` with discovery loop (find→scrape→process→score, repeat until `min_recommended_jobs` unique companies met), curated ATS seed companies (46 verified, 17 India-tagged), hard location filter with Indian city alias expansion (Bangalore↔Bengaluru, Mumbai↔Bombay, etc.), company deduplication in aggregator, incremental job accumulation in scraper, preference enrichment from resume, scoring improvements (recency dimension, company tier context, improved calibration). Settings: `top_k_semantic=40`, `max_jobs_per_company=2`, `max_discovery_iterations=5`, `min_recommended_jobs=10`. New files: `adaptive_pipeline.py`, `ats_seed_companies.py`. 409 unit tests, 90%+ coverage.
- Phase 14: llm-gateway integration — replaced `anthropic` + `instructor` direct usage with `llm-gateway[anthropic]` package. `BaseAgent` now uses `LLMClient` with `_build_llm_client()` seam (single patch target). Removed `extract_token_usage()`, `TOKEN_PRICES`, `FakeInstructorClient`, `_raw_response` hacks. Cost tracking uses `TokenUsage` from llm-gateway. `make_settings()` uses `llm_provider="fake"` (no patches needed for agent construction). Dry-run patches reduced from 2 targets to 1. 54 `AsyncAnthropic`/`instructor` patches removed from 9 test files. `local_claude` live tests (free, no API key). 331 unit tests, 90%+ coverage.
- Phase 13: Vendor-agnostic tool abstractions + test infrastructure hardening — `SearchProvider` and `PageScraper` Protocol interfaces, DuckDuckGo search implementation (free, no API key), tool factory functions (`create_search_provider`, `create_page_scraper`), agents refactored to use factories, `activate_integration_patches()` for LLM-only mocking, `make_real_settings()` for real Postgres/Redis in tests, real scraping integration tests (`test_pipeline_real_scraping.py`), CI pipeline hardening (wait step, container health checks, env vars, artifact upload), run report generation from OTEL spans (`run_report.py`), `pipeline_tracing` fixture for auto-generating run reports in tests, spec files updated
- Phase 12c: Production hardening — Pydantic v2 data converter for Temporal serialization, `result_type` on `execute_activity()` calls, `asyncio.gather(return_exceptions=True)` for resilient parallel scraping, `run_result` checkpoint serialization for output file persistence, embedded worker mode with `AsyncExitStack` + queue deduplication, Docker healthcheck fix for container networking, 90% coverage gate (pre-commit + CI + pyproject.toml), 11 new edge-case unit tests (328 total, 90%+ coverage)
- Phase 12b: Pre-merge hardening — fixed Temporal workflow determinism (`workflow.time()` not `time.monotonic()`), added mypy to pre-commit hook matching CI, aligned ruff version in `.pre-commit-config.yaml` with lockfile (v0.15.2), fixed misleading docstrings, refactored 70-line `run()` into loop-based pattern, split 432-line test file, lazy Temporal health check in conftest (no 30s penalty), fixed resource leak in `check_temporal_available`, proper TLS misconfiguration warning, derive workflow status from errors (`partial` vs `success`), log non-dict errors instead of silently dropping, fixed weak CLI test assertion
- Phase 12: Temporal orchestration — Temporal workflow/activities wrapping existing agents, per-company parallel scraping, TemporalOrchestrator (no silent fallback, raises `TemporalConnectionError`), Temporal client factory (plain TCP/mTLS/API key auth), worker CLI command (`job-hunter worker --queue`), docker-compose Temporal service + UI, `make dev-temporal` / `make run-temporal` / `make worker`, unit tests (client, workflow, orchestrator, activities), integration tests, `--temporal` CLI flag, Temporal as CI service container with E2E validation
- Phase 11: Component spec files — 11 spec files in `docs/specs/` + `docs/SPEC_INDEX.md` for AI context switching. Each spec documents public API, data flow, dependencies, configuration, error handling, testing, and modification patterns.
- Phase 10b: OTEL tracing wiring — pipeline produces root span + per-agent child spans with cost/error attributes, `get_tracer()` / `configure_tracing_with_exporter()` / `disable_tracing()` helpers, `--trace` CLI flag for OTLP, Jaeger in docker-compose (trace profile), `make dev-trace` / `make run-trace`, InMemorySpanExporter integration tests, 4 new unit tests for tracing helpers
- Phase 10: Integration & E2E testing — fixture data (sample_resume.pdf, LLM/ATS/search/HTML fixtures), named fake tools (mock_tools.py), FakeLLMDispatcher (mock_llm.py), dry-run module (dryrun.py), CLI --dry-run mocks all externals, integration tests (DB repos, Redis cache, pipeline dry-run, checkpoint persistence, CLI dry-run), live E2E tests with cost guardrails, Makefile targets (test-e2e, test-live), e2e pytest marker
- Phase 9: Open source standards — README.md, GitHub Actions CI (lint/test/docker jobs), .pre-commit-config.yaml (ruff + pre-commit-hooks), CONTRIBUTING.md (setup, workflow, architecture rules, ATS/agent checklists), SECURITY.md, issue templates (bug report, ATS support request), CHANGELOG.md updated
- Phase 8: Docker + local dev — multi-stage Dockerfile (python:3.12-slim, uv, Playwright Chromium), docker-compose with postgres (pgvector:pg16) + redis (7-alpine) + app service (profiles: full), self-documenting Makefile (help, dev, dev-down, docker-build, docker-run, docker-run-lite, format, clean-docker), .dockerignore, uv.lock now tracked, .env.example Docker section
- Phase 7: Testing — shared test factories (mock_settings, mock_factories), 53 new tests covering PipelineState serialization, checkpoint I/O, BaseAgent (_call_llm, _track_cost, _record_error), Pipeline orchestration, CLI entrypoint; 217 total tests passing, zero ruff warnings
- Phase 6: Observability — structlog config (JSON/console), OTEL tracing (none/console/otlp), LangSmith env setup, CostTracker + extract_token_usage, wired cost tracking into _call_llm, pipeline run context + tracing + cost summary, 27 new tests
- Rectification: Aligned PLAN.md and CLAUDE.md with actual code; removed stale Temporal references from MVP sections; updated cache references from diskcache to Redis/DB
- Phase 5: Agent implementations — BaseAgent with instructor/tenacity, 8 agents, 5 prompt templates, sequential async pipeline with checkpoints, typer CLI
- Cache migration: Replaced diskcache with Redis (default) + DB-backed cache (--lite fallback)
- Phase 4: Tools layer — PDF parser, ATS clients (Greenhouse/Lever/Ashby/Workday), web scraper (crawl4ai + Playwright), web search (Tavily), embedder (local + Voyage + cached), email sender (SMTP + SendGrid)
- Phase 3: Infrastructure layer (DB, cache, vector similarity)
- Phase 2: Core models, config, interfaces, and state
- Phase 1: Project scaffold and monorepo structure
- Phase 0: Created CLAUDE.md and PLAN.md
