# CLAUDE.md — job-hunter-agent

## What This Repo Does
Monorepo for an autonomous multi-agent job discovery system. Accepts a resume PDF and freeform job preferences, discovers target companies, scrapes their official career pages, scores jobs against the candidate's profile using LLM reasoning, and outputs a ranked CSV/Excel with scores, fit reports, and apply URLs. Optionally emails results to the candidate.

## Architecture
- **Monorepo** with four packages under `src/`: `job_hunter_core`, `job_hunter_agents`, `job_hunter_infra`, `job_hunter_cli`
- **AD-1**: PostgreSQL + pgvector for relational + vector storage (no standalone vector DB)
- **AD-2**: Async pipeline with JSON checkpoint files for crash recovery (MVP); Temporal planned for Phase 2
- **AD-3**: Redis for persistent caching (default), DB-backed cache fallback for `--lite` mode. diskcache removed.
- **AD-4**: Local sentence-transformers embeddings by default; Voyage API optional
- **AD-5**: `--lite` mode uses SQLite + local embeddings, zero Docker dependencies
- **AD-6**: instructor library for structured LLM output via Anthropic SDK
- **AD-7**: crawl4ai for career page scraping (Playwright under the hood)
- **AD-8**: Docker image ~3-4GB (PyTorch + Chromium); CPU-only torch wheels deferred
- **6 layers**: Entry/CLI -> Orchestrator -> Parsing -> Company Discovery -> Scraping -> Matching/Output
- LangGraph used only inside CompanyFinderAgent and JobsScorerAgent for multi-step LLM reasoning
- Top-level pipeline is a simple async sequential pipeline, NOT LangGraph

## Build & Run
```bash
# Native (local Python)
make install                             # uv sync + playwright
make test                                # unit tests
make lint                                # ruff + mypy
make run ARGS='resume.pdf --prefs "..."' # run with postgres + redis
make run-trace ARGS='resume.pdf --prefs "..."' # run with OTLP tracing (Jaeger)
make run-lite ARGS='resume.pdf --prefs "..." --dry-run'  # SQLite, no Docker

# Docker
make dev                                 # start postgres + redis
make dev-trace                           # start postgres + redis + Jaeger
make dev-down                            # stop infra
make docker-build                        # build image
make docker-run ARGS='--prefs "..."'     # run in full Docker (resume in data/)
make docker-run-lite ARGS='--prefs "..."' # run lite in Docker
```

## Key Files
- `src/job_hunter_core/models/` — All Pydantic domain models
- `src/job_hunter_core/config/settings.py` — pydantic-settings configuration
- `src/job_hunter_agents/agents/` — All 8 agent implementations
- `src/job_hunter_agents/orchestrator/pipeline.py` — Pipeline with checkpoints
- `src/job_hunter_agents/prompts/` — Versioned LLM prompt templates
- `src/job_hunter_agents/tools/` — PDF parser, ATS clients, scraper, search, embedder
- `src/job_hunter_infra/db/` — SQLAlchemy ORM, repositories, migrations
- `src/job_hunter_infra/cache/` — Redis + DB-backed cache implementations
- `src/job_hunter_agents/orchestrator/pipeline.py` — Sequential async pipeline with checkpoints
- `src/job_hunter_agents/orchestrator/checkpoint.py` — Checkpoint serialization/deserialization
- `src/job_hunter_cli/main.py` — typer CLI entrypoint

## Dependencies
- **LLM**: Anthropic API (Claude Haiku + Sonnet) via `anthropic` + `instructor`
- **Search**: Tavily API for web search
- **Scraping**: crawl4ai + Playwright
- **PDF**: docling (primary), pdfplumber (fallback)
- **Database**: SQLAlchemy async, asyncpg (Postgres), aiosqlite (SQLite)
- **Vector**: pgvector (Postgres mode), NumPy brute-force (SQLite mode)
- **Embeddings**: sentence-transformers (local), Voyage API (optional)
- **Cache**: redis (default), DB-backed (fallback for --lite)
- **Email**: SendGrid or SMTP via aiosmtplib
- **CLI**: typer + rich
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

## Known Issues / TODOs
- Phases 0-10 complete (core, infra, tools, agents, pipeline, CLI, observability, testing, Docker, open source standards, integration & E2E testing)
- Temporal orchestration deferred to Phase 2 (post-MVP)
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
- Unit tests: LLM calls mocked with MagicMock, HTTP mocked in-process
- Integration tests: dry-run patches mock LLM/search/scraping, real DB + cache via Docker
- Live E2E tests: real APIs, company_limit=1, cost guardrail < $2.00
- Fixtures: `tests/fixtures/` has sample PDF, LLM response JSONs, ATS responses, HTML
- Fakes: `tests/mocks/mock_tools.py` (named tool fakes), `tests/mocks/mock_llm.py` (LLM dispatcher)
- Coverage target: 80%

## Recent Changes
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
