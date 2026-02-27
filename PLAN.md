# Temporal Integration Plan

## Requirements Summary

1. **Flexible Temporal connectivity** — works with any URL (self-hosted or Temporal Cloud) with optional authentication (mTLS, API key)
2. **Checkpoint fallback** — if Temporal is not configured or unavailable, fall back to existing checkpoint-based pipeline
3. **Integration/dry-run tests** — spin up Temporal dev server locally (like Docker for DB/cache)
4. **Unit tests** — mock the Temporal service layer entirely

---

## Architecture Decision

### Orchestrator Abstraction

Introduce a common `Orchestrator` protocol that both the existing `Pipeline` (checkpoint-based) and the new `TemporalOrchestrator` implement. The CLI selects the orchestrator based on configuration.

```
CLI
 └─> Settings.orchestrator = "checkpoint" | "temporal"
      ├─> "checkpoint" → Pipeline (existing, unchanged)
      └─> "temporal"   → TemporalOrchestrator → starts workflow via Temporal Client
```

### Temporal Architecture

```
                   ┌───────────────────────────┐
                   │    Temporal Server         │
                   │  (any URL + auth)          │
                   └─────────┬─────────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───────┐ ┌───▼────────┐ ┌──▼─────────────┐
     │ default queue   │ │ llm queue  │ │ scraping queue  │
     │ (parse, agg,   │ │ (company   │ │ (jobs_scraper)  │
     │  notify)       │ │  finder,   │ │                 │
     │                │ │  scorer)   │ │                 │
     └────────────────┘ └────────────┘ └─────────────────┘
```

Each existing agent's `.run()` method becomes a Temporal **activity**. The workflow defines the step ordering, per-company parallelism for scraping, and retry policies.

---

## Implementation Plan — Files to Create/Modify

### Phase 1: Core Config + Exceptions (2 files modified)

#### 1.1 `src/job_hunter_core/config/settings.py` — Add Temporal settings
Add new settings section:
```python
# --- Temporal ---
orchestrator: str = "checkpoint"          # "checkpoint" | "temporal"
temporal_address: str = "localhost:7233"   # Temporal server address
temporal_namespace: str = "default"        # Temporal namespace
temporal_task_queue: str = "job-hunter-default"
temporal_llm_task_queue: str = "job-hunter-llm"
temporal_scraping_task_queue: str = "job-hunter-scraping"
temporal_tls_cert_path: str | None = None  # mTLS cert for Temporal Cloud
temporal_tls_key_path: str | None = None   # mTLS key for Temporal Cloud
temporal_api_key: SecretStr | None = None  # API key auth (Temporal Cloud)
temporal_workflow_timeout_seconds: int = 1800  # 30 min total workflow timeout
```

Add validator:
```python
@model_validator(mode="after")
def validate_temporal_config(self) -> Settings:
    if self.orchestrator == "temporal":
        if self.temporal_tls_cert_path and not Path(self.temporal_tls_cert_path).exists():
            raise ValueError(f"TLS cert not found: {self.temporal_tls_cert_path}")
        if self.temporal_tls_key_path and not Path(self.temporal_tls_key_path).exists():
            raise ValueError(f"TLS key not found: {self.temporal_tls_key_path}")
    return self
```

#### 1.2 `src/job_hunter_core/exceptions.py` — Add TemporalConnectionError
```python
class TemporalConnectionError(JobHunterError):
    """Raised when Temporal server is unreachable."""
```

---

### Phase 2: Temporal Client Factory (1 new file)

#### 2.1 `src/job_hunter_agents/orchestrator/temporal_client.py` — Client creation + fallback logic

```python
"""Temporal client factory with connection testing and fallback."""

async def create_temporal_client(settings: Settings) -> temporalio.client.Client:
    """Create a Temporal client from settings.

    Supports:
    - Plain TCP (self-hosted, no auth)
    - mTLS (Temporal Cloud with cert/key)
    - API key (Temporal Cloud with API key header)

    Raises TemporalConnectionError if server unreachable.
    """

async def check_temporal_available(settings: Settings) -> bool:
    """Test if Temporal server is reachable. Returns False on failure."""
```

Key behaviors:
- Reads `temporal_address`, `temporal_namespace` from settings
- If `temporal_tls_cert_path` + `temporal_tls_key_path` set → mTLS connection
- If `temporal_api_key` set → API key auth via RPC metadata
- Connection test: attempt `client.list_schedules()` or similar lightweight RPC
- On failure: log warning, raise `TemporalConnectionError`

---

### Phase 3: Activities (1 new file)

#### 3.1 `src/job_hunter_agents/orchestrator/temporal_activities.py` — Activity wrappers

Each activity wraps an existing agent's `.run()` method. Activities receive/return serializable payloads (not `PipelineState` directly — too large for Temporal payloads).

```python
"""Temporal activities wrapping existing agent .run() methods."""

from temporalio import activity

@activity.defn
async def parse_resume_activity(payload: ParseResumeInput) -> ParseResumeOutput:
    """Wrap ResumeParserAgent.run()."""

@activity.defn
async def parse_prefs_activity(payload: ParsePrefsInput) -> ParsePrefsOutput:
    """Wrap PrefsParserAgent.run()."""

@activity.defn
async def find_companies_activity(payload: FindCompaniesInput) -> FindCompaniesOutput:
    """Wrap CompanyFinderAgent.run()."""

@activity.defn
async def scrape_company_activity(payload: ScrapeCompanyInput) -> ScrapeCompanyOutput:
    """Wrap JobsScraperAgent.run() for a SINGLE company."""
    # Key difference: per-company granularity for parallelism

@activity.defn
async def process_jobs_activity(payload: ProcessJobsInput) -> ProcessJobsOutput:
    """Wrap JobProcessorAgent.run()."""

@activity.defn
async def score_jobs_activity(payload: ScoreJobsInput) -> ScoreJobsOutput:
    """Wrap JobsScorerAgent.run()."""

@activity.defn
async def aggregate_activity(payload: AggregateInput) -> AggregateOutput:
    """Wrap AggregatorAgent.run()."""

@activity.defn
async def notify_activity(payload: NotifyInput) -> NotifyOutput:
    """Wrap NotifierAgent.run()."""
```

Activity payload models (Pydantic, serializable):
```python
# Input/output dataclasses for each activity
# These are thin wrappers that convert to/from PipelineState fields
```

Each activity:
1. Reconstructs the agent via `AgentClass(settings)` using activity-local settings
2. Builds a minimal `PipelineState` from the input payload
3. Calls `agent.run(state)`
4. Extracts the relevant output fields and returns them
5. Cost/token tracking aggregated back in the workflow via heartbeats or return values

---

### Phase 4: Workflow Definition (1 new file)

#### 4.1 `src/job_hunter_agents/orchestrator/temporal_workflow.py` — Workflow

```python
"""Temporal workflow for the job hunter pipeline."""

from temporalio import workflow

@workflow.defn
class JobHuntWorkflow:
    """Durable workflow orchestrating the 8-step job hunt pipeline."""

    @workflow.run
    async def run(self, config_payload: WorkflowInput) -> WorkflowOutput:
        # Step 1: parse_resume
        profile = await workflow.execute_activity(
            parse_resume_activity,
            ParseResumeInput(resume_path=..., settings_snapshot=...),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3, backoff_coefficient=2.0),
            task_queue=config_payload.default_queue,
        )

        # Step 2: parse_prefs
        preferences = await workflow.execute_activity(
            parse_prefs_activity, ...,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
            task_queue=config_payload.default_queue,
        )

        # Step 3: find_companies
        companies = await workflow.execute_activity(
            find_companies_activity, ...,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue=config_payload.llm_queue,
        )

        # Step 4: scrape_jobs — PARALLEL per company
        scrape_futures = []
        for company in companies.companies:
            scrape_futures.append(
                workflow.execute_activity(
                    scrape_company_activity,
                    ScrapeCompanyInput(company=company, ...),
                    start_to_close_timeout=timedelta(minutes=3),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                    task_queue=config_payload.scraping_queue,
                )
            )
        scrape_results = await asyncio.gather(*scrape_futures)
        raw_jobs = [job for result in scrape_results for job in result.jobs]

        # Step 5: process_jobs
        normalized = await workflow.execute_activity(
            process_jobs_activity, ...,
            start_to_close_timeout=timedelta(minutes=5),
            task_queue=config_payload.llm_queue,
        )

        # Step 6: score_jobs
        scored = await workflow.execute_activity(
            score_jobs_activity, ...,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue=config_payload.llm_queue,
        )

        # Step 7: aggregate
        output = await workflow.execute_activity(
            aggregate_activity, ...,
            start_to_close_timeout=timedelta(minutes=2),
            task_queue=config_payload.default_queue,
        )

        # Step 8: notify
        await workflow.execute_activity(
            notify_activity, ...,
            start_to_close_timeout=timedelta(minutes=1),
            task_queue=config_payload.default_queue,
        )

        return WorkflowOutput(status="success", ...)
```

Key design choices:
- **Per-company parallelism** in Step 4 (biggest perf win)
- **Retry policies** per activity (not global)
- **Task queue routing** — LLM-heavy activities to `llm` queue, scraping to `scraping` queue
- **Cost tracking** — each activity returns token/cost data; workflow aggregates
- **Cost guardrail** — workflow checks cumulative cost after each step, cancels remaining activities if exceeded

---

### Phase 5: Temporal Orchestrator (1 new file)

#### 5.1 `src/job_hunter_agents/orchestrator/temporal_orchestrator.py` — Orchestrator facade

```python
"""Temporal orchestrator — starts workflow and returns result."""

class TemporalOrchestrator:
    """Starts a Temporal workflow and waits for result."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run(self, config: RunConfig) -> RunResult:
        """Start JobHuntWorkflow and wait for result.

        Falls back to Pipeline (checkpoint) if Temporal is unreachable.
        """
        try:
            client = await create_temporal_client(self.settings)
        except TemporalConnectionError:
            logger.warning("temporal_unavailable_falling_back_to_checkpoint")
            pipeline = Pipeline(self.settings)
            return await pipeline.run(config)

        result = await client.execute_workflow(
            JobHuntWorkflow.run,
            WorkflowInput.from_run_config(config, self.settings),
            id=config.run_id,
            task_queue=self.settings.temporal_task_queue,
            execution_timeout=timedelta(
                seconds=self.settings.temporal_workflow_timeout_seconds,
            ),
        )
        return result.to_run_result()
```

**Fallback behavior**: If `TemporalConnectionError` is raised during client creation, log a warning and transparently fall back to the existing `Pipeline` class. This satisfies the "checkpoint as fallback" requirement.

---

### Phase 6: Worker CLI Command (1 file modified)

#### 6.1 `src/job_hunter_cli/main.py` — Add `worker` command + modify `run` command

```python
@app.command()
def worker(
    queue: str = typer.Option("default", "--queue", help="Task queue to poll"),
    ...
) -> None:
    """Start a Temporal worker for the specified task queue."""
    # Map queue name to actual queue string from settings
    # Register activities for that queue
    # Start worker.run() (blocking)

@app.command()  # Modified existing run command
def run(..., temporal: bool = typer.Option(False, "--temporal", help="Use Temporal orchestrator")):
    # If temporal flag or settings.orchestrator == "temporal":
    #   Use TemporalOrchestrator
    # Else:
    #   Use Pipeline (existing behavior, unchanged)
```

---

### Phase 7: Activity Payload Models (1 new file)

#### 7.1 `src/job_hunter_agents/orchestrator/temporal_payloads.py` — Serializable I/O models

```python
"""Pydantic models for Temporal activity inputs/outputs."""

class WorkflowInput(BaseModel):
    """Input to the JobHuntWorkflow."""
    run_id: str
    resume_path: str
    preferences_text: str
    dry_run: bool = False
    force_rescrape: bool = False
    company_limit: int | None = None
    lite_mode: bool = False
    default_queue: str
    llm_queue: str
    scraping_queue: str
    # Settings snapshot (non-secret fields needed by activities)
    settings_snapshot: dict[str, Any]

class WorkflowOutput(BaseModel):
    """Output of the JobHuntWorkflow."""
    status: str
    companies_attempted: int
    companies_succeeded: int
    jobs_scraped: int
    jobs_scored: int
    jobs_in_output: int
    output_files: list[str]
    email_sent: bool
    total_tokens_used: int
    estimated_cost_usd: float
    duration_seconds: float
    errors: list[dict[str, Any]]

class ParseResumeInput(BaseModel): ...
class ParseResumeOutput(BaseModel): ...
# ... one pair per activity
```

---

### Phase 8: Docker & Makefile Updates (3 files modified)

#### 8.1 `docker-compose.yml` — Add Temporal dev server service
```yaml
  temporal:
    image: temporalio/auto-setup:latest
    ports:
      - "7233:7233"      # gRPC frontend
      - "8233:8233"      # Temporal UI
    environment:
      - DB=sqlite         # Use SQLite for dev (no extra DB needed)
    profiles:
      - temporal
      - full
    healthcheck:
      test: ["CMD", "tctl", "--address", "temporal:7233", "cluster", "health"]
      interval: 10s
      timeout: 5s
      retries: 10
```

#### 8.2 `Makefile` — Add Temporal targets
```makefile
dev-temporal: ## Start postgres + redis + temporal
	docker compose --profile temporal up -d --wait

run-temporal: ## Run with Temporal orchestrator
	uv run job-hunter run $(ARGS) --temporal

worker: ## Start Temporal worker (QUEUE=default|llm|scraping)
	uv run job-hunter worker --queue $(QUEUE)
```

#### 8.3 `pyproject.toml` — Add temporalio dependency
```toml
"temporalio>=1.7,<2.0",
```

---

### Phase 9: Tests — Unit (3 new files)

#### 9.1 `tests/unit/orchestrator/test_temporal_client.py`
- Mock `temporalio.client.Client.connect()`
- Test plain TCP, mTLS, API key auth configurations
- Test `check_temporal_available()` returns False on connection failure
- Test `TemporalConnectionError` raised appropriately

#### 9.2 `tests/unit/orchestrator/test_temporal_workflow.py`
- Use `temporalio.testing.WorkflowEnvironment` (Temporal's built-in test framework)
- Mock all activities
- Test successful 8-step execution
- Test per-company parallel scraping
- Test cost guardrail halts workflow
- Test activity failure + retry behavior
- Test workflow timeout

#### 9.3 `tests/unit/orchestrator/test_temporal_orchestrator.py`
- Mock `create_temporal_client` to return mock client
- Test workflow is started with correct parameters
- Test fallback to Pipeline when `TemporalConnectionError` raised
- Test RunResult conversion from WorkflowOutput

---

### Phase 10: Tests — Integration (2 new files)

#### 10.1 `tests/integration/conftest.py` — Add Temporal fixtures
```python
# Add to existing conftest.py:

skip_no_temporal = pytest.mark.skipif(
    not _tcp_reachable("localhost", 7233),
    reason="Temporal not running (run 'make dev-temporal')",
)

@pytest.fixture(scope="session")
async def temporal_client():
    """Connect to local Temporal dev server."""
    client = await Client.connect("localhost:7233")
    yield client

@pytest.fixture
async def temporal_worker(temporal_client, dry_run_patches):
    """Start an in-process worker for integration tests."""
    # Register all activities with dry-run patches active
    # Use unique task queue per test to avoid interference
```

#### 10.2 `tests/integration/test_temporal_pipeline.py`
- Requires `make dev-temporal` (Temporal dev server running)
- Starts in-process worker with dry-run patches
- Executes full workflow end-to-end
- Verifies WorkflowOutput fields (status, counts, cost)
- Tests workflow resume after simulated worker restart
- Tests per-company parallel execution (verify timing)
- Tests fallback behavior when Temporal unavailable

---

### Phase 11: Documentation Updates (3 files modified)

#### 11.1 `CLAUDE.md` — Add Temporal section
- Update Architecture section with orchestrator abstraction
- Add Temporal to Build & Run section
- Update Dependencies section
- Add to Recent Changes

#### 11.2 `.env.example` — Add Temporal env vars
```
# --- Temporal ---
JH_ORCHESTRATOR=checkpoint          # checkpoint | temporal
JH_TEMPORAL_ADDRESS=localhost:7233
JH_TEMPORAL_NAMESPACE=default
JH_TEMPORAL_TASK_QUEUE=job-hunter-default
# JH_TEMPORAL_TLS_CERT_PATH=        # mTLS cert for Temporal Cloud
# JH_TEMPORAL_TLS_KEY_PATH=         # mTLS key for Temporal Cloud
# JH_TEMPORAL_API_KEY=               # API key for Temporal Cloud
```

#### 11.3 `docs/specs/SPEC_04.md` — Add Temporal orchestration section

---

## File Change Summary

| File | Action | Lines (est.) |
|------|--------|-------------|
| `src/job_hunter_core/config/settings.py` | Modify | +30 |
| `src/job_hunter_core/exceptions.py` | Modify | +5 |
| `src/job_hunter_agents/orchestrator/temporal_client.py` | **New** | ~80 |
| `src/job_hunter_agents/orchestrator/temporal_payloads.py` | **New** | ~150 |
| `src/job_hunter_agents/orchestrator/temporal_activities.py` | **New** | ~200 |
| `src/job_hunter_agents/orchestrator/temporal_workflow.py` | **New** | ~120 |
| `src/job_hunter_agents/orchestrator/temporal_orchestrator.py` | **New** | ~60 |
| `src/job_hunter_cli/main.py` | Modify | +50 |
| `docker-compose.yml` | Modify | +15 |
| `Makefile` | Modify | +12 |
| `pyproject.toml` | Modify | +2 |
| `tests/unit/orchestrator/test_temporal_client.py` | **New** | ~80 |
| `tests/unit/orchestrator/test_temporal_workflow.py` | **New** | ~150 |
| `tests/unit/orchestrator/test_temporal_orchestrator.py` | **New** | ~80 |
| `tests/integration/conftest.py` | Modify | +30 |
| `tests/integration/test_temporal_pipeline.py` | **New** | ~120 |
| `CLAUDE.md` | Modify | +20 |
| `.env.example` | Modify | +10 |

**Total: 10 new files, 8 modified files, ~1200 lines**

---

## Design Decisions

### D1: Activity granularity — per-agent (not per-LLM-call)
Each agent becomes one activity. This keeps the mapping 1:1 with existing code and avoids splitting agent logic across multiple activities. The exception is `scrape_jobs` which becomes per-company for parallelism.

### D2: Settings passed via snapshot, not env vars in workers
Activities receive a `settings_snapshot` dict in their payload. This avoids requiring all workers to have identical environment variables and makes testing easier. Secrets (API keys) are the exception — workers must have these in their environment.

### D3: Fallback is transparent — same RunResult type
Both `Pipeline.run()` and `TemporalOrchestrator.run()` return `RunResult`. The CLI doesn't know which orchestrator ran. Fallback from Temporal to checkpoint is automatic and logged.

### D4: Temporal dev server for integration tests (not testcontainers)
Use `temporalio/auto-setup:latest` Docker image in docker-compose with SQLite backend. Same pattern as Postgres/Redis. Tests skip if Temporal isn't running.

### D5: Unit tests use Temporal's built-in test framework
`temporalio.testing.WorkflowEnvironment` provides an in-process mock server. No Docker needed for unit tests. Activities are mocked.

### D6: No changes to existing agent code
All 8 agents remain unchanged. Activities wrap agent `.run()` methods. This means the checkpoint pipeline continues to work identically.

---

## Execution Order

1. **Config + Exceptions** (settings.py, exceptions.py)
2. **Payload models** (temporal_payloads.py) — needed by everything else
3. **Client factory** (temporal_client.py) — tests can start here
4. **Activities** (temporal_activities.py)
5. **Workflow** (temporal_workflow.py)
6. **Orchestrator** (temporal_orchestrator.py)
7. **CLI + Docker + Makefile** (main.py, docker-compose.yml, Makefile, pyproject.toml)
8. **Unit tests** (3 test files)
9. **Integration tests** (conftest + test file)
10. **Docs** (CLAUDE.md, .env.example, SPEC_04)

---

## Phase 12b: Pre-merge Hardening (completed)

Code review before merging to main identified 15 issues. All fixed:

### Critical
- **Temporal determinism**: Replaced `time.monotonic()` with `workflow.time()` in `temporal_workflow.py` — `time.monotonic()` is non-deterministic and breaks Temporal workflow replay

### Source code fixes
- **Misleading docstrings**: Removed "cached per process" claim from `_get_settings()`, removed "cost guardrail enforcement" claim from module docstring
- **Type annotations**: Replaced 3 `Any` return types with proper `Settings`, `PipelineState` types using `TYPE_CHECKING` imports
- **Resource leak**: `check_temporal_available()` now closes the gRPC channel after testing connectivity
- **TLS misconfiguration**: Warns when only one of cert/key path is set (was silently falling back to no TLS)
- **Silent error dropping**: `_to_run_result()` now logs non-dict errors instead of silently discarding
- **Status derivation**: `_build_output()` returns `"partial"` when errors exist (was hardcoded `"success"`)
- **Function length**: Refactored 71-line `run()` into loop-based pattern with `_run_and_extract()` helper
- **Mutation pattern**: `_scrape_parallel()` returns `(tokens, cost)` tuple instead of redundant `(snapshot, tokens, cost)`

### Test/infra fixes
- **30s penalty**: Temporal health check in conftest is now lazy + cached (max 3s only when needed)
- **Unused fixture**: Removed `temporal_client` fixture from conftest
- **Weak assertion**: CLI test asserts `exit_code == 0` (was `in (0, 1)` which always passes)
- **File split**: `test_repositories.py` (432 lines) split into two files under 300 lines each
- **Dryrun test mypy errors**: Replaced direct imports with `importlib` + `getattr` pattern

### CI/DevOps
- **Pre-commit hook**: Added mypy to `scripts/pre-commit` and `.pre-commit-config.yaml`, now mirrors CI lint job exactly
- **Ruff version alignment**: Updated `.pre-commit-config.yaml` from v0.8.6 to v0.15.2 to match lockfile
- **Coverage target**: Updated CLAUDE.md to reflect actual 85% threshold (was 80%)

---

## Phase 15: Adaptive Pipeline Quality Improvements (In Progress)

### Goal
Make the pipeline produce at least 10 scored jobs from unique companies, all
location-relevant (India/Bangalore/Remote), with posted dates and specific apply
URLs, under $5 cost per run.

### Completed Fixes
1. Company tiering, posted_date extraction, apply_url fix (Phase 1-3 of plan)
2. Scoring improvements: recency dimension, better calibration (Phase 6)
3. Preference enrichment from resume (Phase 5)
4. Adaptive discovery loop (Phase 7)
5. Hard location filter with Indian city alias expansion
6. Company deduplication in aggregator (best job per company)
7. Unique company counting in adaptive loop
8. Incremental job accumulation in scraper (preserves partial results on timeout)
9. 6 new India-relevant ATS seed companies (Rubrik, Tekion, Razorpay, Commvault,
   Tower Research Capital, IMC Trading)
10. Increased top_k_semantic 25→40, max_discovery_iterations 3→5
11. Seed ratio increased to ~67% of company slots
12. Empty-location non-remote job exclusion

### Current Status
- Pipeline run_20260227_141103: iteration 0 scored 9 above threshold from 20,
  iterations 1-2 in progress
- 409 unit tests passing, 90%+ coverage
- All lint + type checks pass

### Remaining Work
- Verify pipeline meets all GOAL.md criteria
- If not, consider: lowering score threshold, adding more seed companies,
  excluding known non-ATS companies from LLM generation
- Update CLAUDE.md Recent Changes section
- Commit changes
