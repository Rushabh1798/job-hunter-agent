# SPEC_11: CLI and DevOps

## Purpose

Composition root and development infrastructure: CLI entrypoint that wires settings/logging/tracing and starts the pipeline, plus Makefile, Docker, CI, pre-commit hooks, and the test mock infrastructure used by all test files.

## Key Files

| File | Primary Exports | Lines |
|------|----------------|-------|
| `src/job_hunter_cli/main.py` | `app` (typer), `run()`, `version()` | 131 |
| `Makefile` | 18 targets | 88 |
| `Dockerfile` | Multi-stage build (builder + runtime) | 85 |
| `docker-compose.yml` | postgres, redis, app, jaeger services | ~55 |
| `.github/workflows/ci.yml` | lint, test, docker jobs | 62 |
| `.pre-commit-config.yaml` | pre-commit-hooks, ruff | 17 |
| `pyproject.toml` | Dependencies, tool config | ~200 |
| `.env.example` | 25+ env vars documented | 48 |
| `tests/mocks/mock_settings.py` | `make_settings()` | 36 |
| `tests/mocks/mock_factories.py` | 11 factory functions | 155 |
| `tests/mocks/mock_llm.py` | `FakeInstructorClient`, `build_fake_response()` | 95 |
| `tests/mocks/mock_tools.py` | 9 fake tool classes | 208 |

## Public API

### CLI (`src/job_hunter_cli/main.py`)

```python
app = typer.Typer(name="job-hunter", help="Autonomous multi-agent job discovery system")

@app.command()
def run(
    resume: Path,                          # positional, must exist
    prefs: str = "",                       # --prefs
    prefs_file: Path | None = None,        # --prefs-file
    dry_run: bool = False,                 # --dry-run
    force_rescrape: bool = False,          # --force-rescrape
    company_limit: int | None = None,      # --company-limit
    lite: bool = False,                    # --lite
    resume_from: str | None = None,        # --resume-from
    trace: bool = False,                   # --trace
    verbose: bool = False,                 # -v/--verbose
) -> None

@app.command()
def version() -> None
```

**CLI Flow:**
1. Resolve preferences (--prefs text or --prefs-file content)
2. Build `RunConfig` from all flags
3. Create `Settings()` from environment
4. Apply overrides: `--lite` sets sqlite/local/db; `--verbose` sets DEBUG; `--trace` sets otlp
5. `configure_logging(settings)`, `configure_tracing(settings)`
6. If `--dry-run`: import and activate dry-run patches (lazy import)
7. `Pipeline(settings).run(config)` via `asyncio.run()`
8. Print result summary (companies, jobs, cost, duration, output files)
9. Exit code 1 if `result.status != "success"`

### Makefile Targets

| Target | Command | Description |
|--------|---------|-------------|
| `help` | `grep -E` | Show all targets with descriptions |
| `install` | `uv sync && playwright install chromium` | Install deps + browser |
| `dev` | `docker compose up -d` + health checks | Start postgres + redis |
| `dev-trace` | `docker compose --profile trace up -d` + health checks | Start postgres + redis + Jaeger |
| `dev-down` | `docker compose down` | Stop all services |
| `test` | `pytest -m unit` | Unit tests only |
| `test-int` | `make dev && pytest -m integration` | Start infra + integration tests |
| `test-e2e` | `pytest -m "e2e or live" -v` | E2E + live tests |
| `test-live` | `pytest -m live -v` | Live API tests |
| `test-all` | `pytest` | All tests |
| `lint` | `ruff check . && mypy .` | Linter + type checker |
| `format` | `ruff format . && ruff check --fix .` | Auto-format |
| `run` | `uv run job-hunter run $(ARGS)` | Run CLI |
| `run-trace` | `uv run job-hunter run --trace $(ARGS)` | Run CLI with OTLP |
| `run-lite` | `JH_DB_BACKEND=sqlite JH_CACHE_BACKEND=db uv run job-hunter run --lite $(ARGS)` | Run lite |
| `docker-build` | `docker build -t job-hunter-agent:latest .` | Build image |
| `docker-run` | `docker compose --profile full run --rm app run ...` | Run in Docker |
| `docker-run-lite` | `docker run --rm ... --lite $(ARGS)` | Run lite in Docker |
| `clean` | `find . -type d -name __pycache__ -exec rm -rf {} +` | Remove caches |
| `clean-docker` | `docker compose --profile full down -v` | Remove containers + volumes |

### Dockerfile

**Stage 1 — builder:**
- Base: `python:3.12-slim`
- Installs build-essential, gcc, libffi-dev
- Copies uv from `ghcr.io/astral-sh/uv:latest`
- `uv sync --frozen --no-dev` (deps only, then with project)

**Stage 2 — runtime:**
- Base: `python:3.12-slim`
- Installs Playwright Chromium runtime deps (libnss3, libatk, etc.)
- Creates non-root user `appuser` (uid 1000)
- Copies .venv, src, pyproject.toml from builder
- `playwright install chromium`
- Sets `PLAYWRIGHT_BROWSERS_PATH=/app/.browsers`
- Health check: `python -c "from job_hunter_cli.main import app; print('ok')"`
- Entrypoint: `job-hunter`, CMD: `--help`

### Docker Compose Services

| Service | Image | Ports | Profile | Health Check |
|---------|-------|-------|---------|-------------|
| postgres | `pgvector/pgvector:pg16` | 5432 | (default) | `pg_isready` |
| redis | `redis:7-alpine` | 6379 | (default) | `redis-cli ping` |
| app | Built from `Dockerfile` | — | `full` | — |
| jaeger | `jaegertracing/all-in-one:latest` | 4317, 4318, 16686 | `trace` | — |

### CI Pipeline (`.github/workflows/ci.yml`)

**Triggers:** push/PR to main, with concurrency grouping.

| Job | Steps | Depends On |
|-----|-------|-----------|
| `lint` | checkout, setup-uv, setup-python 3.12, `uv sync`, ruff check, ruff format --check, mypy | — |
| `test` | checkout, setup-uv, setup-python 3.12, `uv sync`, playwright install, `pytest -m unit --cov --cov-fail-under=80`, upload coverage | — |
| `docker` | checkout, `docker build` | lint + test |

### Pre-commit Hooks (`.pre-commit-config.yaml`)

| Hook | Version | Purpose |
|------|---------|---------|
| `trailing-whitespace` | pre-commit-hooks v5.0.0 | Remove trailing spaces |
| `end-of-file-fixer` | " | Ensure final newline |
| `check-yaml` | " | Validate YAML |
| `check-added-large-files` | " | Reject files >500KB |
| `ruff` | ruff-pre-commit v0.8.6 | Lint + auto-fix |
| `ruff-format` | " | Format check |

---

### Mock Infrastructure

#### `make_settings()` (`tests/mocks/mock_settings.py`)

Returns a `MagicMock` with all Settings fields pre-set:

```python
def make_settings(**overrides: object) -> MagicMock:
    # Pre-set fields:
    settings.anthropic_api_key.get_secret_value.return_value = "test-key"
    settings.haiku_model = "claude-haiku-4-5-20251001"
    settings.sonnet_model = "claude-sonnet-4-5-20250514"
    settings.max_cost_per_run_usd = 5.0
    settings.warn_cost_threshold_usd = 2.0
    settings.checkpoint_enabled = False
    settings.checkpoint_dir = Path("/tmp/checkpoints")
    settings.agent_timeout_seconds = 300
    settings.log_level = "INFO"
    settings.db_backend = "sqlite"
    settings.embedding_provider = "local"
    settings.cache_backend = "db"
    settings.otel_exporter = "none"
    settings.otel_endpoint = "http://localhost:4317"
    settings.otel_service_name = "job-hunter-test"
```

#### Factory Functions (`tests/mocks/mock_factories.py`)

| Function | Returns | Key Defaults |
|----------|---------|-------------|
| `make_run_config(**overrides)` | `RunConfig` | run_id="test-run-001", resume_path=/tmp/test_resume.pdf |
| `make_pipeline_state(**overrides)` | `PipelineState` | Default RunConfig, all fields empty |
| `make_candidate_profile(**overrides)` | `CandidateProfile` | name="Jane Doe", skills=[Python, SQL] |
| `make_search_preferences(**overrides)` | `SearchPreferences` | remote_preference="remote", target_titles=["Software Engineer"] |
| `make_company(**overrides)` | `Company` | name="Acme Corp", domain="acme.com" |
| `make_raw_job(company_id, **overrides)` | `RawJob` | company_name="Acme Corp", strategy="crawl4ai" |
| `make_normalized_job(company_id, raw_job_id, **overrides)` | `NormalizedJob` | title="Software Engineer" |
| `make_scored_job(job, **overrides)` | `ScoredJob` | score=85, recommendation="good_match" |
| `make_agent_error(**overrides)` | `AgentError` | agent_name="test_agent", error_type="ValueError" |

All functions accept `**overrides` to replace any default field.

#### `FakeInstructorClient` (`tests/mocks/mock_llm.py`)

Routes `_call_llm` responses to fixture JSON files by `response_model` class name:

| response_model Class | Fixture File |
|---------------------|-------------|
| `CandidateProfile` | `tests/fixtures/llm_responses/candidate_profile.json` |
| `SearchPreferences` | `tests/fixtures/llm_responses/search_preferences.json` |
| `CompanyCandidateList` | `tests/fixtures/llm_responses/company_candidates.json` |
| `ExtractedJob` | `tests/fixtures/llm_responses/extracted_job.json` |
| `BatchScoreResult` | `tests/fixtures/llm_responses/batch_score.json` |

Each fixture has `{"_meta": {"input_tokens": N, "output_tokens": N}, "data": {...}}`. The `_meta` is attached as `instance._raw_response.usage` so `extract_token_usage()` works.

#### Fake Tool Classes (`tests/mocks/mock_tools.py`)

| Fake Class | Real Class | Behavior |
|-----------|-----------|----------|
| `FakePDFParser` | `PDFParser` | Returns `tests/fixtures/resume_text.txt` |
| `FakeWebSearchTool` | `WebSearchTool` | Returns `tests/fixtures/search_results/career_page_search.json` |
| `FakeWebScraper` | `WebScraper` | Returns `tests/fixtures/html/career_page.html` |
| `FakeGreenhouseClient` | `GreenhouseClient` | Real regex detect + fixture `greenhouse_jobs.json` |
| `FakeLeverClient` | `LeverClient` | Real regex detect + fixture `lever_jobs.json` |
| `FakeAshbyClient` | `AshbyClient` | Real regex detect + fixture `ashby_jobs.json` |
| `FakeWorkdayClient` | `WorkdayClient` | Real regex detect + empty list (no API) |
| `FakeEmailSender` | `EmailSender` | Records calls in `self.calls` for assertion |
| `FakeEmbedder` | `LocalEmbedder` | Deterministic 384-dim vectors from text hash |

### Fixture Files

| Directory | Files | Purpose |
|-----------|-------|---------|
| `tests/fixtures/` | `sample_resume.pdf`, `resume_text.txt` | PDF parsing inputs |
| `tests/fixtures/llm_responses/` | 5 JSON files | LLM response fixtures |
| `tests/fixtures/ats_responses/` | `greenhouse_jobs.json`, `lever_jobs.json`, `ashby_jobs.json` | ATS API responses |
| `tests/fixtures/html/` | `career_page.html` | Web scraping fixture |
| `tests/fixtures/search_results/` | `career_page_search.json` | Tavily search results |

## Internal Dependencies

- `job_hunter_core.config.settings.Settings` — created in CLI, passed to Pipeline
- `job_hunter_core.models.run.RunConfig` — built from CLI args
- `job_hunter_agents.observability.configure_logging`, `configure_tracing` — called at startup
- `job_hunter_agents.orchestrator.pipeline.Pipeline` — instantiated and run
- `job_hunter_agents.dryrun.activate_dry_run_patches` — lazy import for --dry-run

## External Dependencies

- `typer>=0.9` — CLI framework
- `rich>=13.0` — Console output formatting
- `docker` — Container runtime for dev/CI
- `uv` — Package manager
- `ruff>=0.8` — Linting + formatting
- `mypy>=1.13` — Type checking
- `pytest>=8.0`, `pytest-asyncio>=0.24`, `pytest-cov>=5.0`, `pytest-mock>=3.14` — Testing

## Data Flow

```
CLI args → RunConfig + Settings
    → configure_logging(settings)
    → configure_tracing(settings)
    → [if dry_run] activate_dry_run_patches()
    → Pipeline(settings).run(config)
    → RunResult
    → Print summary + exit code
```

## Configuration

All configuration flows through `Settings` (see SPEC_01). The CLI applies these overrides:

| Flag | Settings Override |
|------|------------------|
| `--lite` | `db_backend="sqlite"`, `embedding_provider="local"`, `cache_backend="db"` |
| `--verbose` | `log_level="DEBUG"` |
| `--trace` | `otel_exporter="otlp"` |

## Error Handling

- Missing `--prefs` or `--prefs-file`: prints error, exits with code 1
- Pipeline failure (`result.status != "success"`): exits with code 1
- `activate_dry_run_patches()` wrapped in try/finally to ensure `patch_stack.close()`

## Testing

| Test File | What It Tests |
|-----------|--------------|
| `tests/unit/cli/test_main.py` | CLI command parsing, flag handling, exit codes |
| `tests/integration/test_cli_dryrun.py` | Full CLI with --dry-run flag end-to-end |

## Common Modification Patterns

### Add a new CLI flag
1. Add parameter to `run()` function in `main.py` with `typer.Option()`
2. If it maps to a Settings field, add override logic (like `if trace: settings.otel_exporter = "otlp"`)
3. If it maps to RunConfig, add field to `RunConfig` in SPEC_01
4. Add test in `test_main.py`

### Add a new Makefile target
1. Add target with `## description` comment (for `make help`)
2. Add to `.PHONY` line
3. Follow existing patterns (health check waits for docker services, `$(ARGS)` for CLI passthrough)

### Add a new test mock
1. Create named class in `tests/mocks/mock_tools.py` (match real class interface)
2. Add fixture file in `tests/fixtures/` if needed
3. Add patch target in `src/job_hunter_agents/dryrun.py` (see SPEC_04)
4. Add fixture mapping in `mock_llm.py` if it's an LLM response type

### Add a new LLM fixture
1. Create JSON in `tests/fixtures/llm_responses/<name>.json` with `{"_meta": {"input_tokens": N, "output_tokens": N}, "data": {...}}`
2. Add entry to `_FIXTURE_MAP` in `mock_llm.py`: `"ClassName": "filename.json"`

### Modify Docker build
1. Edit `Dockerfile` — builder stage for deps, runtime stage for execution
2. Keep non-root user (`appuser`)
3. Keep health check command
4. Test with `make docker-build`

## Cross-References

- **SPEC_01** — Settings, RunConfig models
- **SPEC_04** — Pipeline, dryrun module
- **SPEC_10** — configure_logging, configure_tracing called from CLI
