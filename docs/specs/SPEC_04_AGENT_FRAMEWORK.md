# SPEC_04: Agent Framework

## Purpose

Defines the agent execution framework: the `BaseAgent` abstract class with LLM integration, cost tracking, and error recording; the `Pipeline` sequential orchestrator with checkpoint-based crash recovery; the `checkpoint` module for serializing/deserializing pipeline state to JSON files; and the `dryrun` module that replaces all external I/O with named fakes for testing and `--dry-run` CLI mode.

## Key Files

| File | Primary Exports | Lines |
|------|----------------|-------|
| `src/job_hunter_agents/agents/base.py` | `BaseAgent` (ABC) | 163 |
| `src/job_hunter_agents/orchestrator/pipeline.py` | `Pipeline`, `PIPELINE_STEPS` | 202 |
| `src/job_hunter_agents/orchestrator/checkpoint.py` | `save_checkpoint()`, `load_latest_checkpoint()` | 61 |
| `src/job_hunter_agents/dryrun.py` | `activate_dry_run_patches()` | 132 |

## Public API

### BaseAgent (`agents/base.py`)

```python
T = TypeVar("T", bound=BaseModel)

class BaseAgent(ABC):
    """Abstract base class for all pipeline agents."""

    agent_name: str = "base"   # Override in each subclass

    def __init__(self, settings: Settings) -> None
    # Creates:
    #   self.settings = settings
    #   self._client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
    #   self._instructor = instructor.from_anthropic(self._client)

    @abstractmethod
    async def run(self, state: PipelineState) -> PipelineState
    # Each agent implements this. Receives mutable state, returns mutated state.

    def _log_start(self, context: dict[str, object] | None = None) -> None
    # Emits structlog INFO: event="agent_start", agent=self.agent_name, **context

    def _log_end(self, duration: float, context: dict[str, object] | None = None) -> None
    # Emits structlog INFO: event="agent_end", agent=self.agent_name, duration_seconds=...

    async def _call_llm(
        self,
        messages: list[dict[str, str]],
        model: str,
        response_model: type[T],
        max_retries: int = 3,
        state: PipelineState | None = None,
    ) -> T

    def _track_cost(
        self,
        state: PipelineState,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> None

    def _record_error(
        self,
        state: PipelineState,
        error: Exception,
        is_fatal: bool = False,
        company_name: str | None = None,
        job_id: str | None = None,
    ) -> None
```

#### `_call_llm()` -- Detailed Behavior

This is the central LLM calling method used by every agent. It integrates instructor for structured output, tenacity for retries, token extraction for cost tracking, and structured logging.

**Step-by-step flow:**

1. **Define inner retry function.** A nested `_do_call()` async function is decorated with `@retry` from tenacity:
   - `stop=stop_after_attempt(max_retries)` -- defaults to 3 attempts.
   - `wait=wait_exponential(multiplier=1, min=1, max=10)` -- exponential backoff between 1s and 10s.
   - `reraise=True` -- the final exception propagates to the caller (not wrapped in `RetryError`).

2. **Call instructor.** Inside `_do_call()`, the call is:
   ```python
   response: T = await self._instructor.messages.create(
       model=model,
       max_tokens=4096,
       messages=messages,
       response_model=response_model,
   )
   ```
   The `instructor` library wraps the Anthropic `AsyncAnthropic` client. It sends the request to the Anthropic API, receives the raw response, and validates/parses it into the Pydantic `response_model` class `T`. If the response does not conform to the schema, instructor retries internally (separate from the tenacity retry). The `max_tokens` is hardcoded to 4096 for all agent calls.

3. **Measure elapsed time.** `time.monotonic()` is used to bracket the `_do_call()` invocation. The duration covers all retry attempts.

4. **Extract token usage.** Calls `extract_token_usage(result)` from the observability module:
   ```python
   input_tokens, output_tokens = extract_token_usage(result)
   ```
   `extract_token_usage()` reads `result._raw_response.usage.input_tokens` and `result._raw_response.usage.output_tokens`. This attribute chain is set by instructor, which attaches the raw Anthropic API response as `_raw_response` on the Pydantic model instance. Returns `(0, 0)` if the attribute chain is missing (e.g., in tests without a properly mocked `_raw_response`).

5. **Track cost (conditional).** If `state is not None`, calls `self._track_cost(state, input_tokens, output_tokens, model)`. When `state` is `None` (e.g., a standalone LLM call not associated with a pipeline run), cost tracking is skipped.

6. **Log completion.** Emits a structlog DEBUG event:
   ```python
   logger.debug(
       "llm_call_complete",
       agent=self.agent_name,
       model=model,
       duration=round(elapsed, 2),
       input_tokens=input_tokens,
       output_tokens=output_tokens,
   )
   ```

7. **Return result.** Returns the Pydantic model instance `T`.

**Error propagation:** If all retry attempts fail, the original exception (API error, validation error, network error) is reraised due to `reraise=True`. The caller (the concrete agent's `run()` method) is responsible for catching and recording errors via `_record_error()`, or letting them propagate to the pipeline's error handlers.

#### `_track_cost()` -- Detailed Behavior

Accumulates token usage and enforces cost guardrails on every LLM call.

1. **Accumulate tokens.** Adds `input_tokens + output_tokens` to `state.total_tokens`.

2. **Compute cost.** Looks up `model` in `TOKEN_PRICES` (from `job_hunter_core.constants`). If the model is known:
   ```python
   cost = input_tokens * prices["input"] / 1_000_000
        + output_tokens * prices["output"] / 1_000_000
   ```
   Prices are in USD per 1M tokens. The computed cost is added to `state.total_cost_usd`. If the model is not in `TOKEN_PRICES`, tokens are still accumulated but cost remains unchanged.

3. **Hard cost limit.** If `state.total_cost_usd > self.settings.max_cost_per_run_usd`, raises `CostLimitExceededError` immediately. This error propagates up through `_call_llm()` to the pipeline's `_run_agent_step()`, which catches it and returns a `RunResult` with `status="partial"`.

4. **Warning threshold.** If `state.total_cost_usd > self.settings.warn_cost_threshold_usd` (but below the hard limit), emits a structlog WARNING with `current_cost` and `limit` fields.

**Current `TOKEN_PRICES` map:**

| Model | Input ($/1M tokens) | Output ($/1M tokens) |
|-------|---------------------|----------------------|
| `claude-haiku-4-5-20251001` | 0.80 | 4.00 |
| `claude-sonnet-4-5-20250514` | 3.00 | 15.00 |

#### `_record_error()` -- Detailed Behavior

Records a non-fatal or fatal error into the pipeline state for later reporting.

1. Constructs an `AgentError` Pydantic model:
   - `agent_name` = `self.agent_name`
   - `error_type` = `type(error).__name__`
   - `error_message` = `str(error)`
   - `company_name` = optional, for company-scoped errors
   - `job_id` = optional `UUID`, for job-scoped errors
   - `is_fatal` = whether the error should halt the pipeline
   - `timestamp` = auto-set via `datetime.now(UTC)` default factory

2. Appends the `AgentError` to `state.errors`.

3. Emits a structlog ERROR event with `agent`, `error_type`, `error`, and `is_fatal` fields.

---

### Pipeline (`orchestrator/pipeline.py`)

#### `PIPELINE_STEPS` Registry

An ordered list of `(step_name, agent_class)` tuples defining the fixed sequential execution order:

| Index | Step Name | Agent Class | Purpose |
|-------|-----------|-------------|---------|
| 0 | `parse_resume` | `ResumeParserAgent` | Extract structured candidate profile from PDF |
| 1 | `parse_prefs` | `PrefsParserAgent` | Parse freeform preferences into structured search criteria |
| 2 | `find_companies` | `CompanyFinderAgent` | Discover target companies via web search + ATS detection |
| 3 | `scrape_jobs` | `JobsScraperAgent` | Scrape raw job listings from career pages / ATS APIs |
| 4 | `process_jobs` | `JobProcessorAgent` | Normalize raw jobs into structured format via LLM |
| 5 | `score_jobs` | `JobsScorerAgent` | Score normalized jobs against candidate profile |
| 6 | `aggregate` | `AggregatorAgent` | Generate output files (CSV, XLSX) |
| 7 | `notify` | `NotifierAgent` | Send email notification with results |

```python
PIPELINE_STEPS: list[tuple[str, type[BaseAgent]]] = [
    ("parse_resume", ResumeParserAgent),
    ("parse_prefs", PrefsParserAgent),
    ("find_companies", CompanyFinderAgent),
    ("scrape_jobs", JobsScraperAgent),
    ("process_jobs", JobProcessorAgent),
    ("score_jobs", JobsScorerAgent),
    ("aggregate", AggregatorAgent),
    ("notify", NotifierAgent),
]
```

#### Pipeline Class

```python
class Pipeline:
    """Sequential async pipeline with crash recovery via checkpoint files."""

    def __init__(self, settings: Settings) -> None
    # Stores self.settings

    async def run(self, config: RunConfig) -> RunResult
    async def _run_agent_step(
        self,
        step_name: str,
        agent_cls: type[BaseAgent],
        state: PipelineState,
        pipeline_start: float,
    ) -> PipelineState | RunResult

    @staticmethod
    def _set_root_span_attrs(root_span: object | None, status: str, state: PipelineState) -> None
    @staticmethod
    def _log_cost_summary(state: PipelineState, duration: float) -> None
    def _load_or_create_state(self, config: RunConfig) -> PipelineState
```

#### `Pipeline.run()` -- Detailed Behavior

Entry point for executing the full pipeline.

1. **Record start time.** `start = time.monotonic()`.

2. **Load or create state.** Calls `self._load_or_create_state(config)`, which either restores from a checkpoint or creates a fresh `PipelineState(config=config)`.

3. **Bind observability context.** Calls `bind_run_context(config.run_id)` to set the `run_id` on the structlog context. A `try/finally` block ensures `clear_run_context()` is always called on exit.

4. **Open root tracing span.** Enters `trace_pipeline_run(config.run_id)` async context manager, yielding a `root_span` (or `None` if tracing is disabled).

5. **Iterate PIPELINE_STEPS.** For each `(step_name, agent_cls)`:
   - **Skip completed steps.** If `step_name in state.completed_steps`, logs `"step_skipped"` and continues. The `completed_steps` property on `PipelineState` infers completion from state contents (e.g., `profile is not None` means `parse_resume` is done).
   - **Run agent step.** Calls `_run_agent_step(step_name, agent_cls, state, start)`. This returns either an updated `PipelineState` (on success) or a `RunResult` (on error). If a `RunResult` is returned, it is immediately returned from `run()` -- the pipeline stops early.

6. **Set root span attributes.** After all steps succeed, calls `_set_root_span_attrs(root_span, "success", state)` with summary metrics.

7. **Log cost summary.** Calls `_log_cost_summary(state, duration)`.

8. **Build and return RunResult.** If `state.run_result` was set by an agent (e.g., the AggregatorAgent), returns it with updated `duration_seconds`. Otherwise, calls `state.build_result(status="success", duration_seconds=duration)`.

#### `Pipeline._run_agent_step()` -- Detailed Behavior

Executes a single agent with tracing, timeout, checkpoint saving, and error handling.

1. **Open trace span.** If `get_tracer()` returns a tracer (tracing is enabled), starts a span named `"agent.{step_name}"` with attribute `agent.name`.

2. **Instantiate agent.** `agent = agent_cls(self.settings)`.

3. **Execute with timeout.** Wraps the agent's `run()` in `asyncio.wait_for()`:
   ```python
   state = await asyncio.wait_for(
       agent.run(state),
       timeout=self.settings.agent_timeout_seconds,
   )
   ```

4. **Save checkpoint.** If `self.settings.checkpoint_enabled`, serializes state via `state.to_checkpoint(step_name)` and writes it with `save_checkpoint(checkpoint, self.settings.checkpoint_dir)`.

5. **Set span attributes.** On success, sets `agent.status="ok"` and `agent.tokens` on the span.

6. **Return updated state.** Returns the `PipelineState` for the next iteration.

**Error handling (all caught in `except` blocks):**

| Exception Type | Pipeline Status | Behavior |
|---------------|-----------------|----------|
| `CostLimitExceededError` | `"partial"` | Logs error, logs cost summary, returns `RunResult` with partial results collected so far |
| `FatalAgentError` | `"failed"` | Logs error with step name, logs cost summary, returns `RunResult` |
| `TimeoutError` | `"failed"` | Logs timeout with step name and timeout value, logs cost summary, returns `RunResult` |

All error paths set `agent.status="error"` and `agent.error` on the trace span. The `finally` block always calls `span.end()`.

#### `Pipeline._load_or_create_state()`

1. If `settings.checkpoint_enabled`, calls `load_latest_checkpoint(config.run_id, settings.checkpoint_dir)`.
2. If a checkpoint is found, logs `"resuming_from_checkpoint"` with the completed step name and returns `PipelineState.from_checkpoint(checkpoint)`.
3. Otherwise, returns a fresh `PipelineState(config=config)`.

#### `Pipeline._set_root_span_attrs()`

Sets the following attributes on the root pipeline span (if not `None`):

| Attribute | Value |
|-----------|-------|
| `pipeline.status` | `"success"` (or the status string) |
| `pipeline.total_tokens` | `state.total_tokens` |
| `pipeline.total_cost_usd` | `round(state.total_cost_usd, 4)` |
| `pipeline.jobs_scored` | `len(state.scored_jobs)` |
| `pipeline.errors` | `len(state.errors)` |

#### `Pipeline._log_cost_summary()`

Emits a structlog INFO event `"pipeline_summary"` with fields:
- `total_tokens`, `total_cost_usd` (rounded to 4 decimals), `duration_seconds` (rounded to 2 decimals), `jobs_scored`, `errors` count.

---

### Checkpoint (`orchestrator/checkpoint.py`)

#### `save_checkpoint()`

```python
def save_checkpoint(checkpoint: PipelineCheckpoint, checkpoint_dir: Path) -> Path
```

1. Creates `checkpoint_dir` with `parents=True, exist_ok=True`.
2. Constructs filename: `"{checkpoint.run_id}--{checkpoint.completed_step}.json"`.
3. Writes `checkpoint.model_dump_json(indent=2)` to the file.
4. Logs `"checkpoint_saved"` with path and step.
5. Returns the `Path` to the saved file.
6. On `OSError`, raises `CheckpointError` with context message.

**File naming convention:** `{run_id}--{step_name}.json`

Example: `run_20250201_120000--parse_resume.json`

Multiple checkpoints accumulate per run (one per completed step). The double-dash `--` separator is chosen to avoid ambiguity since `run_id` may contain single hyphens.

#### `load_latest_checkpoint()`

```python
def load_latest_checkpoint(run_id: str, checkpoint_dir: Path) -> PipelineCheckpoint | None
```

1. Returns `None` if `checkpoint_dir` does not exist.
2. Globs for `"{run_id}--*.json"` files in the directory.
3. Sorts matches by `st_mtime` descending (newest first).
4. Returns `None` if no matches found.
5. Reads the newest file, parses JSON, constructs `PipelineCheckpoint(**data)`.
6. Logs `"checkpoint_loaded"` with path and step.
7. On `json.JSONDecodeError` or `OSError`, raises `CheckpointError`.

**Selection strategy:** Most recent by filesystem modification time, not by step order. This means if checkpoint files are manually tampered with, the mtime determines which is loaded.

---

### Dry-Run (`dryrun.py`)

```python
def activate_dry_run_patches() -> ExitStack
```

Activates `unittest.mock.patch()` calls that replace all external I/O constructors with named fake implementations. Returns an `ExitStack` that the caller must close (or use as a context manager) to deactivate all patches.

This function is shared by:
- The `dry_run_patches` pytest fixture in `tests/integration/conftest.py`
- The CLI `--dry-run` mode (patches are activated before pipeline execution)

**Lazy imports:** The fake classes are imported inside the function body to avoid circular dependencies and to keep test-only dependencies out of production import paths.

#### Complete Patch Target Table

| # | Patch Target | Fake Replacement | Source Module | Purpose |
|---|-------------|-----------------|---------------|---------|
| 1 | `job_hunter_agents.agents.resume_parser.PDFParser` | `FakePDFParser` | `tests/mocks/mock_tools.py` | Returns fixture resume text from `tests/fixtures/resume_text.txt` |
| 2 | `job_hunter_agents.agents.company_finder.WebSearchTool` | `FakeWebSearchTool` | `tests/mocks/mock_tools.py` | Returns fixture search results from `tests/fixtures/search_results/career_page_search.json` |
| 3 | `job_hunter_agents.agents.company_finder.GreenhouseClient` | `FakeGreenhouseClient` | `tests/mocks/mock_tools.py` | Detection via real regex; returns fixture jobs from `tests/fixtures/ats_responses/greenhouse_jobs.json` |
| 4 | `job_hunter_agents.agents.company_finder.LeverClient` | `FakeLeverClient` | `tests/mocks/mock_tools.py` | Detection via real regex; returns fixture jobs from `tests/fixtures/ats_responses/lever_jobs.json` |
| 5 | `job_hunter_agents.agents.company_finder.AshbyClient` | `FakeAshbyClient` | `tests/mocks/mock_tools.py` | Detection via real regex; returns fixture jobs from `tests/fixtures/ats_responses/ashby_jobs.json` |
| 6 | `job_hunter_agents.agents.company_finder.WorkdayClient` | `FakeWorkdayClient` | `tests/mocks/mock_tools.py` | Detection via real regex; returns empty list (Workday has no standard API) |
| 7 | `job_hunter_agents.agents.jobs_scraper.GreenhouseClient` | `FakeGreenhouseClient` | `tests/mocks/mock_tools.py` | Same fake as #3, patched at scraper import location |
| 8 | `job_hunter_agents.agents.jobs_scraper.LeverClient` | `FakeLeverClient` | `tests/mocks/mock_tools.py` | Same fake as #4, patched at scraper import location |
| 9 | `job_hunter_agents.agents.jobs_scraper.AshbyClient` | `FakeAshbyClient` | `tests/mocks/mock_tools.py` | Same fake as #5, patched at scraper import location |
| 10 | `job_hunter_agents.agents.jobs_scraper.WorkdayClient` | `FakeWorkdayClient` | `tests/mocks/mock_tools.py` | Same fake as #6, patched at scraper import location |
| 11 | `job_hunter_agents.agents.jobs_scraper.WebScraper` | `FakeWebScraper` | `tests/mocks/mock_tools.py` | Returns fixture HTML from `tests/fixtures/html/career_page.html` |
| 12 | `job_hunter_agents.agents.notifier.EmailSender` | `FakeEmailSender` | `tests/mocks/mock_tools.py` | Records calls for assertion; returns `True` without sending |
| 13 | `job_hunter_agents.agents.base.AsyncAnthropic` | `MagicMock` | `unittest.mock` | Prevents real Anthropic API client creation |
| 14 | `job_hunter_agents.agents.base.instructor` | `MagicMock` (configured) | `unittest.mock` + `tests/mocks/mock_llm.py` | `instructor.from_anthropic()` returns `FakeInstructorClient` |

**Patch #14 detail:** A `MagicMock` replaces the entire `instructor` module. Its `from_anthropic` method is configured to return a `FakeInstructorClient` instance. `FakeInstructorClient` has a `messages` attribute with an async `create()` method that routes `response_model` class names to fixture JSON files via `_FIXTURE_MAP`:

| `response_model.__name__` | Fixture File |
|---------------------------|-------------|
| `CandidateProfile` | `tests/fixtures/llm_responses/candidate_profile.json` |
| `SearchPreferences` | `tests/fixtures/llm_responses/search_preferences.json` |
| `CompanyCandidateList` | `tests/fixtures/llm_responses/company_candidates.json` |
| `ExtractedJob` | `tests/fixtures/llm_responses/extracted_job.json` |
| `BatchScoreResult` | `tests/fixtures/llm_responses/batch_score.json` |

Each fixture file has a `_meta` object (with `input_tokens` and `output_tokens`) and a `data` object. The `build_fake_response()` function constructs the Pydantic model from `data` and attaches a fake `_raw_response` with `usage` attributes so that `extract_token_usage()` works correctly even in dry-run mode.

**ATS client fakes:** The four ATS fakes (`FakeGreenhouseClient`, `FakeLeverClient`, `FakeAshbyClient`, `FakeWorkdayClient`) use **real regex detection logic** in their `detect()` methods. This means the dry-run exercises the same ATS detection code path as production -- only the `fetch_jobs()` method returns fixture data instead of making HTTP calls.

**Note on duplicate patches:** ATS clients are patched at two import locations each (once in `company_finder`, once in `jobs_scraper`) because Python's `unittest.mock.patch()` patches the name at the import site, not at the definition site. Both agents import these clients independently.

---

## Internal Dependencies

### From SPEC_01 (Core Models)

| Import | Used By | Purpose |
|--------|---------|---------|
| `PipelineState` | `BaseAgent.run()`, `Pipeline`, checkpoint | Mutable state threaded through the pipeline |
| `RunConfig` | `Pipeline.run()` | Input configuration for a pipeline run |
| `RunResult` | `Pipeline.run()` return type | Summary of completed run |
| `PipelineCheckpoint` | `save_checkpoint()`, `load_latest_checkpoint()` | Serializable checkpoint model |
| `AgentError` | `BaseAgent._record_error()` | Structured error record |
| `Settings` | `BaseAgent.__init__()`, `Pipeline.__init__()` | Application configuration |
| `CostLimitExceededError` | `BaseAgent._track_cost()`, `Pipeline._run_agent_step()` | Cost guardrail exception |
| `FatalAgentError` | `Pipeline._run_agent_step()` | Unrecoverable agent error |
| `CheckpointError` | `save_checkpoint()`, `load_latest_checkpoint()` | Checkpoint I/O failure |
| `TOKEN_PRICES` | `BaseAgent._track_cost()` | Per-model token pricing map |

### From Observability (SPEC_10)

| Import | Used By | Purpose |
|--------|---------|---------|
| `extract_token_usage()` | `BaseAgent._call_llm()` | Extract token counts from instructor response |
| `bind_run_context()` | `Pipeline.run()` | Set run_id on structlog context |
| `clear_run_context()` | `Pipeline.run()` (finally block) | Clear structlog context |
| `get_tracer()` | `Pipeline._run_agent_step()` | Get OpenTelemetry tracer (or None) |
| `trace_pipeline_run()` | `Pipeline.run()` | Async context manager for root pipeline span |

## External Dependencies

| Package | Used By | Purpose |
|---------|---------|---------|
| `anthropic` | `BaseAgent.__init__()` | `AsyncAnthropic` client for Claude API |
| `instructor` | `BaseAgent.__init__()`, `BaseAgent._call_llm()` | Structured output parsing; wraps Anthropic client to validate responses against Pydantic models |
| `tenacity` | `BaseAgent._call_llm()` | Retry decorator with exponential backoff |
| `structlog` | All modules | Structured logging |
| `pydantic` | `BaseAgent._call_llm()` type bound | `BaseModel` as type bound for response models |

## Data Flow

```
RunConfig
   |
   v
Pipeline.run(config)
   |
   +--> _load_or_create_state(config)
   |       |
   |       +--> load_latest_checkpoint(run_id, checkpoint_dir)
   |       |       |
   |       |       +--> [checkpoint found] --> PipelineState.from_checkpoint(cp)
   |       |       +--> [no checkpoint]    --> PipelineState(config=config)
   |       |
   |       v
   |    PipelineState (fresh or restored)
   |
   +--> bind_run_context(run_id)
   |
   +--> trace_pipeline_run(run_id) as root_span
   |
   +--> for (step_name, agent_cls) in PIPELINE_STEPS:
   |       |
   |       +--> [step in completed_steps?] --> skip
   |       |
   |       +--> _run_agent_step(step_name, agent_cls, state, start)
   |               |
   |               +--> agent = agent_cls(settings)
   |               |
   |               +--> asyncio.wait_for(agent.run(state), timeout)
   |               |       |
   |               |       +--> [agent calls _call_llm() internally]
   |               |       |       |
   |               |       |       +--> instructor.messages.create(...)
   |               |       |       +--> extract_token_usage(result)
   |               |       |       +--> _track_cost(state, ...) [if state provided]
   |               |       |       +--> return T (Pydantic model)
   |               |       |
   |               |       +--> [agent mutates state fields]
   |               |       +--> return state
   |               |
   |               +--> save_checkpoint(state.to_checkpoint(step_name), checkpoint_dir)
   |               |
   |               +--> return PipelineState | RunResult (on error)
   |
   +--> _set_root_span_attrs(root_span, "success", state)
   +--> _log_cost_summary(state, duration)
   +--> return RunResult (success/partial/failed)
   |
   +--> [finally] clear_run_context()
```

## Configuration

All settings come from `Settings` (pydantic-settings, env prefix `JH_`). The following fields are directly consumed by the agent framework:

| Setting | Type | Default | Used By |
|---------|------|---------|---------|
| `agent_timeout_seconds` | `int` | `300` | `Pipeline._run_agent_step()` -- per-agent timeout for `asyncio.wait_for()` |
| `checkpoint_enabled` | `bool` | `True` | `Pipeline._run_agent_step()` / `_load_or_create_state()` -- toggles checkpoint save/load |
| `checkpoint_dir` | `Path` | `./output/checkpoints` | `Pipeline._run_agent_step()` / `_load_or_create_state()` -- directory for checkpoint JSON files |
| `max_cost_per_run_usd` | `float` | `5.0` | `BaseAgent._track_cost()` -- hard stop if exceeded |
| `warn_cost_threshold_usd` | `float` | `2.0` | `BaseAgent._track_cost()` -- log warning if exceeded |
| `anthropic_api_key` | `SecretStr` | (required) | `BaseAgent.__init__()` -- passed to `AsyncAnthropic` |
| `haiku_model` | `str` | `claude-haiku-4-5-20251001` | Used by agents when calling `_call_llm()` for fast/cheap tasks |
| `sonnet_model` | `str` | `claude-sonnet-4-5-20250514` | Used by agents when calling `_call_llm()` for high-quality tasks |

## Error Handling

### Exception Hierarchy

All framework-relevant exceptions inherit from `JobHunterError`:

```
JobHunterError
  +-- CostLimitExceededError   (raised by _track_cost)
  +-- FatalAgentError          (raised by agents for unrecoverable errors)
  +-- CheckpointError          (raised by save_checkpoint / load_latest_checkpoint)
```

### Error Handling Flow

| Error | Raised By | Caught By | Resulting Status | Behavior |
|-------|-----------|-----------|------------------|----------|
| `CostLimitExceededError` | `BaseAgent._track_cost()` | `Pipeline._run_agent_step()` | `"partial"` | Pipeline stops gracefully; returns results collected so far; cost summary is logged |
| `FatalAgentError` | Individual agent `run()` methods | `Pipeline._run_agent_step()` | `"failed"` | Pipeline halts immediately; error is logged with step name |
| `TimeoutError` | `asyncio.wait_for()` | `Pipeline._run_agent_step()` | `"failed"` | Logged with step name and configured timeout value |
| `CheckpointError` | `save_checkpoint()` / `load_latest_checkpoint()` | **Not caught by pipeline** | Propagates | Checkpoint I/O failures are not suppressed; they terminate the pipeline |
| Tenacity exhaustion | `_call_llm()` inner `_do_call()` | **Not caught by framework** | Depends on caller | After `max_retries` attempts, the original exception is reraised; the concrete agent must handle it |

### Non-Fatal Error Recording

Agents use `_record_error(state, error, is_fatal=False)` for errors that should not stop the pipeline (e.g., a single company's scrape failing). These are accumulated in `state.errors` and included in the final `RunResult.errors` list. The pipeline continues to the next step.

### Fatal Error Escalation

When an agent encounters an unrecoverable problem (e.g., resume parsing yields no usable content), it raises `FatalAgentError`. The pipeline catches this in `_run_agent_step()` and returns a `RunResult` with `status="failed"`.

### Cost Limit Behavior

The cost guardrail is checked **after every LLM call**, not after every agent step. This means a single agent making multiple LLM calls can trigger the limit mid-execution. The `CostLimitExceededError` propagates out of `_call_llm()` through the agent's `run()` and is caught by `_run_agent_step()`. The pipeline returns a `"partial"` result with whatever data was collected before the limit was hit.

## Testing

### Test Files

| Test File | Tests | Scope |
|-----------|-------|-------|
| `tests/unit/agents/test_base.py` | `TestCallLLM` (4 tests), `TestTrackCost` (5 tests), `TestRecordError` (1 test) | Unit |
| `tests/unit/orchestrator/test_pipeline.py` | `TestPipeline` (9 tests) | Unit |
| `tests/unit/orchestrator/test_checkpoint.py` | `TestSaveCheckpoint` (3 tests), `TestLoadLatestCheckpoint` (4 tests) | Unit |
| `tests/integration/test_pipeline_dryrun.py` | `TestPipelineDryRun` (6 tests) | Integration |
| `tests/integration/test_pipeline_tracing.py` | Pipeline tracing integration tests | Integration |
| `tests/integration/test_checkpoint_persistence.py` | Checkpoint persistence integration tests | Integration |

### How Pipeline Tests Mock Agents

Pipeline unit tests (`test_pipeline.py`) replace the real `PIPELINE_STEPS` with a custom list of lightweight mock agent classes:

```python
class _MockAgentA:
    def __init__(self, settings: object) -> None: ...
    async def run(self, state: PipelineState) -> PipelineState:
        state.total_tokens += 10
        return state

MOCK_STEPS = [("step_a", _MockAgentA), ("step_b", _MockAgentB)]
```

A helper `_enter_pipeline_patches()` applies all necessary patches via `ExitStack`:
- Replaces `PIPELINE_STEPS` with the mock steps
- Replaces `trace_pipeline_run` with a no-op async context manager
- Mocks `bind_run_context`, `clear_run_context`, `save_checkpoint`, `load_latest_checkpoint`, `get_tracer`

For error-path tests, `_make_error_steps()` creates single-step pipelines with agents whose `run()` raises specific exceptions (`CostLimitExceededError`, `FatalAgentError`, `TimeoutError`).

### How Base Tests Mock Instructor

Base agent unit tests (`test_base.py`) use a `_StubAgent` concrete subclass with a no-op `run()`. Agent creation is wrapped in `_create_stub_agent()` which patches:
- `AsyncAnthropic` -- prevents real API client creation
- `instructor` module -- prevents real instructor wrapping

Individual tests then configure `agent._instructor.messages.create` as an `AsyncMock` returning `_DummyResponse` instances, and patch `extract_token_usage` to return controlled `(input_tokens, output_tokens)` tuples.

### How Integration Tests Use Dry-Run

Integration tests in `test_pipeline_dryrun.py` use the `dry_run_patches` fixture from `tests/integration/conftest.py`:

```python
@pytest.fixture
def dry_run_patches() -> Generator[ExitStack, None, None]:
    from job_hunter_agents.dryrun import activate_dry_run_patches
    stack = activate_dry_run_patches()
    yield stack
    stack.close()
```

This activates all 14 patches from `activate_dry_run_patches()`, runs the full 8-agent pipeline with fixture data, and verifies end-to-end behavior (output files generated, cost tracked, checkpoints saved).

### Shared Test Infrastructure

| Module | Exports | Purpose |
|--------|---------|---------|
| `tests/mocks/mock_settings.py` | `make_settings(**overrides)` | Factory for `MagicMock` `Settings` with sensible defaults |
| `tests/mocks/mock_factories.py` | `make_pipeline_state()`, `make_run_config()`, etc. | Factory functions for domain model instances |
| `tests/mocks/mock_llm.py` | `FakeInstructorClient`, `build_fake_response()` | Fixture-based LLM response simulation |
| `tests/mocks/mock_tools.py` | `FakePDFParser`, `FakeWebSearchTool`, `FakeWebScraper`, `Fake*Client`, `FakeEmailSender`, `FakeEmbedder` | Named fake tool implementations |

## Common Modification Patterns

### Add a new agent to the pipeline

1. Create a new agent class in `src/job_hunter_agents/agents/new_agent.py` that inherits from `BaseAgent`.
2. Set `agent_name: str = "new_agent_name"` as a class attribute.
3. Implement the `async def run(self, state: PipelineState) -> PipelineState` method.
4. Import the new agent in `src/job_hunter_agents/orchestrator/pipeline.py`.
5. Add a tuple `("step_name", NewAgent)` to the `PIPELINE_STEPS` list at the desired position.
6. If the new agent uses external I/O tools, add corresponding `patch()` calls in `src/job_hunter_agents/dryrun.py`:
   - Import the fake tool class (create one in `tests/mocks/mock_tools.py` if needed).
   - Add `stack.enter_context(patch("job_hunter_agents.agents.new_agent.ToolClass", FakeToolClass))`.
7. If the new agent calls `_call_llm()` with a new `response_model`, add a fixture JSON file in `tests/fixtures/llm_responses/` and register it in `_FIXTURE_MAP` in `tests/mocks/mock_llm.py`.
8. Update `PipelineState.completed_steps` property in `src/job_hunter_core/state.py` to detect when the new step has been completed (based on state field contents).
9. Add unit tests in `tests/unit/agents/test_new_agent.py`.

### Modify pipeline step order

1. Edit the `PIPELINE_STEPS` list in `src/job_hunter_agents/orchestrator/pipeline.py` to reorder tuples.
2. Verify that the `PipelineState.completed_steps` property still correctly infers step completion in the new order. The property uses data-presence checks (not step order), so reordering agents that produce/consume the same data fields may cause checkpoint resume to skip or re-run steps incorrectly.
3. Delete any existing checkpoint files from previous runs, as they may resume at the wrong step.
4. Update integration tests in `tests/integration/test_pipeline_dryrun.py` if assertions depend on step ordering.

### Add a new error handling case

1. Define a new exception class in `src/job_hunter_core/exceptions.py`, inheriting from `JobHunterError`.
2. To handle it at the pipeline level (in `_run_agent_step()`), add a new `except` block in `src/job_hunter_agents/orchestrator/pipeline.py`:
   ```python
   except NewExceptionType as e:
       logger.error("new_error_type", step=step_name, error=str(e))
       # set span attributes...
       duration = time.monotonic() - pipeline_start
       self._log_cost_summary(state, duration)
       return state.build_result(status="...", duration_seconds=duration)
   ```
3. To handle it at the agent level (recorded but non-fatal), use `self._record_error(state, error, is_fatal=False)` inside the agent's `run()` method and continue execution.
4. Add test coverage for the new error path in `tests/unit/orchestrator/test_pipeline.py` using the `_make_error_steps()` helper.

## Cross-References

- **SPEC_01: Core Models** -- `PipelineState`, `RunConfig`, `RunResult`, `PipelineCheckpoint`, `AgentError`, `Settings`, all exception classes, `TOKEN_PRICES`
- **SPEC_10: Observability** -- `extract_token_usage()`, `bind_run_context()`, `clear_run_context()`, `get_tracer()`, `trace_pipeline_run()`, `CostTracker`, `LLMCallMetrics`
- **Individual Agent Specs** -- Each concrete agent (ResumeParserAgent through NotifierAgent) inherits from `BaseAgent` and is registered in `PIPELINE_STEPS`
- **CLI Spec** -- The CLI entry point creates a `Pipeline` instance and calls `pipeline.run(config)`. In `--dry-run` mode, it activates `activate_dry_run_patches()` before execution.
