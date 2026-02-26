# SPEC_10: Observability

## Purpose

This spec covers the observability subsystem: structured logging, distributed tracing, and LLM cost tracking. These three concerns are isolated in the `observability` package and wired into the pipeline at two levels: (1) the `Pipeline` orchestrator binds run context, creates root spans, and logs cost summaries; (2) `BaseAgent._call_llm()` extracts token usage from each LLM response and updates cost state. The design ensures that observability is zero-cost when disabled (`otel_exporter=none`, no LangSmith key) and that all OTEL imports are deferred so `--lite` mode never loads heavy tracing dependencies.

## Key Files

| File | Role |
|------|------|
| `src/job_hunter_agents/observability/__init__.py` | Re-exports all public symbols from the four submodules |
| `src/job_hunter_agents/observability/logging.py` | `configure_logging`, `bind_run_context`, `clear_run_context` |
| `src/job_hunter_agents/observability/tracing.py` | OTEL tracing setup, `traced_agent` decorator, `trace_pipeline_run` context manager |
| `src/job_hunter_agents/observability/cost_tracker.py` | `LLMCallMetrics`, `CostTracker`, `extract_token_usage` |
| `src/job_hunter_agents/observability/run_report.py` | `RunReport`, `AgentStep`, `MOCK_MANIFESTS`, `generate_run_report()`, `format_run_report()` |
| `src/job_hunter_agents/agents/base.py` | Integrates cost tracking via `_track_cost()` and `extract_token_usage()` in `_call_llm()` |
| `src/job_hunter_agents/orchestrator/pipeline.py` | Integrates all three: `bind_run_context`/`clear_run_context`, `trace_pipeline_run`, `get_tracer`, `_log_cost_summary` |
| `src/job_hunter_core/config/settings.py` | Observability-related settings fields |
| `src/job_hunter_core/constants.py` | `TOKEN_PRICES` dict for cost calculation |
| `src/job_hunter_core/exceptions.py` | `CostLimitExceededError` |
| `tests/unit/observability/test_logging.py` | Unit tests for logging configuration |
| `tests/unit/observability/test_tracing.py` | Unit tests for tracing setup and decorators |
| `tests/unit/observability/test_cost_tracker.py` | Unit tests for cost tracking and token extraction |
| `tests/unit/observability/test_run_report.py` | Unit tests for run report generation and formatting |
| `tests/integration/test_pipeline_tracing.py` | Integration tests for end-to-end OTEL spans |

## Public API

### Logging — `src/job_hunter_agents/observability/logging.py`

```python
def configure_logging(settings: Settings) -> None:
    """Configure structlog with JSON or console rendering.

    Sets up shared processors, routes stdlib logging through structlog,
    and configures the output format based on settings.

    Shared processors (applied in order):
      1. merge_contextvars — merges context vars (run_id, etc.) into each log entry
      2. add_log_level — adds 'level' key
      3. TimeStamper(fmt="iso") — adds ISO-8601 timestamp
      4. StackInfoRenderer — renders stack info if present
      5. UnicodeDecoder — ensures string output

    Renderer selection:
      - settings.log_format == "json" -> JSONRenderer()
      - settings.log_format == "console" -> ConsoleRenderer()

    stdlib integration:
      - Uses ProcessorFormatter.wrap_for_formatter as the final structlog processor
      - Creates ProcessorFormatter for stdlib handlers with:
        - remove_processors_meta (strips structlog metadata)
        - selected renderer
      - Replaces all root logger handlers with a single StreamHandler
      - Sets root logger level from settings.log_level

    Third-party logger quieting:
      - httpx, httpcore, sqlalchemy.engine set to max(configured_level, WARNING)
    """


def bind_run_context(run_id: str) -> None:
    """Bind run_id to all subsequent log entries via structlog contextvars.

    Uses structlog.contextvars.bind_contextvars(run_id=run_id).
    Called at the start of Pipeline.run().
    All log entries from any agent/tool will include this run_id
    until clear_run_context() is called.
    """


def clear_run_context() -> None:
    """Clear all bound context variables.

    Uses structlog.contextvars.clear_contextvars().
    Called in the finally block of Pipeline.run() to prevent
    context leaking between runs.
    """


def _resolve_level(level_name: str) -> int:
    """Convert a level name string to a logging level int.

    Mapping (case-insensitive):
      "DEBUG" -> 10, "INFO" -> 20, "WARNING" -> 30,
      "ERROR" -> 40, "CRITICAL" -> 50
    Unknown names default to INFO (20).
    """
```

### Tracing — `src/job_hunter_agents/observability/tracing.py`

#### Module-level state

```python
_tracer: Any = None
# Module-level variable holding the OTEL Tracer instance.
# Set by configure_tracing() or configure_tracing_with_exporter().
# Reset to None by disable_tracing().
# When None, all tracing functions are no-ops.
# This is the single point of truth for "is tracing enabled?"
```

#### Functions

```python
def configure_tracing(settings: Settings) -> None:
    """Configure OpenTelemetry tracing based on settings.

    Lifecycle:
      1. Call _maybe_init_langsmith(settings) to set LangSmith env vars
      2. If settings.otel_exporter == "none": set _tracer = None, return
      3. Deferred import of opentelemetry SDK modules
      4. Create Resource with service.name = settings.otel_service_name
      5. Create TracerProvider with that Resource
      6. Add span processor based on exporter type:
         - "console": SimpleSpanProcessor(ConsoleSpanExporter())
         - "otlp": BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint))
      7. Set as global tracer provider via trace.set_tracer_provider()
      8. Get tracer via trace.get_tracer("job-hunter-agent")
      9. Assign to module-level _tracer
      10. Log "tracing_configured" event

    All OTEL imports are deferred inside this function so that --lite mode
    (otel_exporter="none") never loads opentelemetry packages.
    """


def traced_agent(
    agent_name: str,
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
    """Async decorator that wraps an agent run in an OTEL span.

    When _tracer is None: passes through to the decorated function (zero overhead).
    When _tracer is active: creates a span named "agent.{agent_name}" with attributes:
      - agent.name: the agent_name parameter
      - agent.status: "ok" on success, "error" on exception
      - agent.error: str(exc) on exception (only set on error)
      - agent.duration_seconds: elapsed time rounded to 3 decimal places
    Re-raises any exception after recording it on the span.

    Note: This decorator is defined but not currently applied via @decorator syntax
    on agent classes. Instead, the Pipeline._run_agent_step() creates spans directly
    using get_tracer().start_span(). The decorator is available for use on
    standalone async functions.
    """


@asynccontextmanager
async def trace_pipeline_run(run_id: str) -> AsyncGenerator[Any, None]:
    """Context manager that creates a root span for the entire pipeline run.

    When _tracer is None: yields None (no-op).
    When _tracer is active: creates span "pipeline.run" with attribute:
      - pipeline.run_id: the run_id parameter
    Yields the span object for the caller to set additional attributes
    (pipeline.status, pipeline.total_tokens, etc.).

    Used in Pipeline.run():
      async with trace_pipeline_run(config.run_id) as root_span:
          # ... execute all steps ...
          self._set_root_span_attrs(root_span, "success", state)
    """


def get_tracer() -> Any:
    """Return the configured tracer, or None if tracing is disabled.

    Used by Pipeline._run_agent_step() to create per-agent child spans.
    Callers must check for None before calling tracer methods.
    """


def configure_tracing_with_exporter(
    service_name: str,
    exporter: Any,
) -> None:
    """Configure tracing with an explicit span exporter.

    Used by tests to inject InMemorySpanExporter without reading Settings.

    Implementation:
      1. Import OTEL SDK (not deferred — tests always have it)
      2. Create Resource with service.name = service_name
      3. Create TracerProvider with that Resource
      4. Add SimpleSpanProcessor with the provided exporter
      5. Get tracer from provider directly (provider.get_tracer, NOT
         from global trace.get_tracer) to avoid conflicts with
         set_tracer_provider when called multiple times in test suites
      6. Assign to module-level _tracer

    Key difference from configure_tracing(): does NOT call
    trace.set_tracer_provider(), avoiding global state pollution in tests.
    """


def disable_tracing() -> None:
    """Reset tracer to disabled state by setting _tracer = None.

    Called in test teardown fixtures and when tracing is not needed.
    """


def _maybe_init_langsmith(settings: Settings) -> None:
    """Set LangSmith env vars if an API key is configured.

    When settings.langsmith_api_key is not None:
      - os.environ["LANGCHAIN_TRACING_V2"] = "true"
      - os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key.get_secret_value()
      - os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    Logs "langsmith_configured" event.

    When settings.langsmith_api_key is None: does nothing.
    """
```

### Cost Tracking — `src/job_hunter_agents/observability/cost_tracker.py`

```python
@dataclass
class LLMCallMetrics:
    """Metrics for a single LLM call."""
    model: str              # Model ID (e.g., "claude-haiku-4-5-20251001")
    input_tokens: int       # Input token count
    output_tokens: int      # Output token count
    duration_seconds: float # Wall-clock duration of the call
    agent_name: str         # Name of the agent that made the call


@dataclass
class CostTracker:
    """Accumulates LLM call metrics and enforces cost guardrails.

    Maintains a list of all LLMCallMetrics recorded during a pipeline run.
    Provides record_call() for real-time tracking and summary() for
    end-of-run reporting.
    """
    calls: list[LLMCallMetrics] = field(default_factory=list)

    def record_call(
        self,
        metrics: LLMCallMetrics,
        state: PipelineState,
        max_cost: float,
        warn_threshold: float,
    ) -> None:
        """Record a call, update state, and enforce cost limits.

        Steps:
          1. Append metrics to self.calls
          2. Add (input_tokens + output_tokens) to state.total_tokens
          3. Look up model in TOKEN_PRICES dict
          4. If found, compute cost:
               cost = input_tokens * prices["input"] / 1_000_000
                    + output_tokens * prices["output"] / 1_000_000
             Add cost to state.total_cost_usd
          5. If state.total_cost_usd > max_cost: raise CostLimitExceededError
          6. If state.total_cost_usd > warn_threshold: log "cost_warning" with
             current_cost, threshold, and limit

        Note: Unknown models (not in TOKEN_PRICES) track tokens but not cost.
        """

    def summary(self) -> dict[str, object]:
        """Return aggregated cost summary for structured logging.

        Returns dict with keys:
          - "total_calls": int — number of LLM calls
          - "total_tokens": int — sum of all input + output tokens
          - "cost_by_model": dict[str, float] — cost broken down by model ID
          - "total_cost_usd": float — sum of all model costs, rounded to 6 decimals

        Returns zeroed values when self.calls is empty.
        """


def extract_token_usage(response: object) -> tuple[int, int]:
    """Extract input/output token counts from an instructor response.

    Instructor wraps the raw Anthropic response in _raw_response.
    Traversal: response._raw_response.usage.{input_tokens, output_tokens}

    Falls back to (0, 0) if any attribute in the chain is missing:
      - response has no _raw_response -> (0, 0)
      - _raw_response has no usage -> (0, 0)

    Returns: (input_tokens: int, output_tokens: int)
    """
```

### Run Report — `src/job_hunter_agents/observability/run_report.py`

Generates a human-readable run report from OTEL spans, showing which components were real vs mocked, agent execution timing, and flow linkage. Primarily used in integration/e2e tests via the `pipeline_tracing` fixture.

```python
MOCK_MANIFESTS: dict[str, dict[str, str]]
# Maps mock mode ("dry_run", "integration", "live") to component status dicts.
# Each component is "mocked" or "real (description)".

@dataclass
class AgentStep:
    order: int
    name: str
    duration_ms: float
    status: str        # "ok" or "error"
    tokens: int
    error: str | None

@dataclass
class RunReport:
    run_id: str
    pipeline_status: str
    total_duration_ms: float
    total_tokens: int
    total_cost_usd: float
    jobs_scored: int
    error_count: int
    mock_mode: str
    component_manifest: dict[str, str]
    agent_steps: list[AgentStep] = field(default_factory=list)

def generate_run_report(spans: list[Any], mock_mode: str = "dry_run") -> RunReport:
    """Build RunReport from finished OTEL spans.
    Finds the root 'pipeline.run' span for summary metrics,
    extracts 'agent.*' child spans for per-agent timing."""

def format_run_report(report: RunReport) -> str:
    """Format RunReport as a human-readable string with sections:
    pipeline summary, component status (MOCK/REAL), agent flow, errors."""
```

**Mock manifests:**

| Mode | LLM | PDF Parser | Search | Scraper | ATS | Email | DB | Cache |
|------|-----|-----------|--------|---------|-----|-------|-----|-------|
| `dry_run` | mocked | mocked | mocked | mocked | mocked | mocked | real (settings) | real (settings) |
| `integration` | mocked | mocked | real (DDG) | real | real (APIs) | mocked | real (Postgres) | real (Redis) |
| `live` | real | real | real (Tavily) | real | real | real | real | real |

**Used by:** `pipeline_tracing` fixture in `tests/integration/conftest.py` — auto-detects mock mode from active fixtures, collects spans from `InMemorySpanExporter`, and prints the formatted report after each test.

---

#### Token Pricing Table (`src/job_hunter_core/constants.py`)

```python
TOKEN_PRICES: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20250514": {"input": 3.00, "output": 15.00},
}
# Prices are in USD per 1 million tokens.
```

## Internal Dependencies

- **`job_hunter_core.config.settings.Settings`** — consumed by `configure_logging()` and `configure_tracing()` for all observability configuration
- **`job_hunter_core.constants.TOKEN_PRICES`** — consumed by `CostTracker.record_call()` and `CostTracker.summary()` for cost calculation
- **`job_hunter_core.exceptions.CostLimitExceededError`** — raised by `CostTracker.record_call()` when cost limit is exceeded
- **`job_hunter_core.state.PipelineState`** — mutated by `CostTracker.record_call()` (total_tokens, total_cost_usd); read by Pipeline for cost summary logging
- **`job_hunter_agents.agents.base.BaseAgent`** — calls `extract_token_usage()` in `_call_llm()` and has its own `_track_cost()` method (parallel implementation to `CostTracker.record_call()`)
- **`job_hunter_agents.orchestrator.pipeline.Pipeline`** — wires logging context, tracing context, and cost summary logging

## External Dependencies

| Package | Used By | Purpose |
|---------|---------|---------|
| `structlog` | logging.py, all modules | Structured logging with JSON/console rendering, contextvars |
| `structlog.contextvars` | logging.py | `bind_contextvars`, `clear_contextvars`, `merge_contextvars` for run_id propagation |
| `structlog.stdlib` | logging.py | `ProcessorFormatter`, `BoundLogger`, `LoggerFactory`, `add_log_level` |
| `opentelemetry-api` | tracing.py | `trace` module for `set_tracer_provider`, `get_tracer` |
| `opentelemetry-sdk` | tracing.py | `TracerProvider`, `Resource`, span processors, `ConsoleSpanExporter` |
| `opentelemetry-exporter-otlp-proto-grpc` | tracing.py | `OTLPSpanExporter` for OTLP gRPC export |
| `opentelemetry-sdk` (test only) | test_tracing.py, test_pipeline_tracing.py | `InMemorySpanExporter` for capturing spans in tests |

All OpenTelemetry imports are **deferred** inside `configure_tracing()` and `configure_tracing_with_exporter()`. When `otel_exporter="none"` (the default), no OTEL packages are imported at all.

## Data Flow

### Logging Context Flow

```
Pipeline.run()
    |
    |--> bind_run_context(config.run_id)
    |      Sets run_id in structlog contextvars.
    |      All subsequent log calls from any module will include run_id.
    |
    |--> [agent execution... all structlog.get_logger() calls include run_id]
    |
    |--> Pipeline._log_cost_summary(state, duration)
    |      Logs "pipeline_summary" with total_tokens, total_cost_usd,
    |      duration_seconds, jobs_scored, errors.
    |
    |--> clear_run_context()  [in finally block]
           Clears all contextvars to prevent leaking between runs.
```

### Tracing Flow

```
configure_tracing(settings) — called once at application startup
    |
    |--> _maybe_init_langsmith(settings)
    |      Sets LANGCHAIN_* env vars if API key present.
    |
    |--> If otel_exporter != "none":
    |      Create TracerProvider + span processor + set global provider
    |      _tracer = trace.get_tracer("job-hunter-agent")
    |
    v
Pipeline.run()
    |
    |--> async with trace_pipeline_run(run_id) as root_span:
    |      Creates root span "pipeline.run" with pipeline.run_id attribute.
    |      root_span is None if _tracer is None.
    |
    |    For each agent step:
    |    |--> Pipeline._run_agent_step()
    |    |      tracer = get_tracer()
    |    |      if tracer: span = tracer.start_span("agent.{step_name}")
    |    |      span.set_attribute("agent.name", step_name)
    |    |      ... execute agent ...
    |    |      span.set_attribute("agent.status", "ok"|"error")
    |    |      span.set_attribute("agent.tokens", state.total_tokens)
    |    |      span.end()  [in finally block]
    |
    |--> _set_root_span_attrs(root_span, "success", state)
           Sets on root span:
             pipeline.status, pipeline.total_tokens, pipeline.total_cost_usd,
             pipeline.jobs_scored, pipeline.errors
```

### Cost Tracking Flow

There are two parallel cost tracking paths. Both update `PipelineState`:

**Path A: BaseAgent._track_cost() (active path in current code)**
```
BaseAgent._call_llm(messages, model, response_model, state)
    |
    |--> instructor.messages.create(...)  [with tenacity retry]
    |
    |--> extract_token_usage(result)
    |      Traverses result._raw_response.usage.{input_tokens, output_tokens}
    |      Returns (input_tokens, output_tokens) or (0, 0) on missing attrs
    |
    |--> if state is not None: _track_cost(state, input_tokens, output_tokens, model)
    |      Adds tokens to state.total_tokens
    |      Looks up TOKEN_PRICES[model] for per-million pricing
    |      Computes cost and adds to state.total_cost_usd
    |      Raises CostLimitExceededError if over settings.max_cost_per_run_usd
    |      Logs warning if over settings.warn_cost_threshold_usd
    |
    |--> logger.debug("llm_call_complete", agent, model, duration, tokens)
```

**Path B: CostTracker.record_call() (available for standalone use)**
```
CostTracker.record_call(metrics, state, max_cost, warn_threshold)
    |
    |--> Append metrics to self.calls
    |--> Update state.total_tokens
    |--> Look up TOKEN_PRICES, compute cost, update state.total_cost_usd
    |--> Enforce max_cost -> CostLimitExceededError
    |--> Warn on warn_threshold
```

**End-of-run summary:**
```
Pipeline._log_cost_summary(state, duration)
    |
    |--> logger.info("pipeline_summary",
    |      total_tokens=state.total_tokens,
    |      total_cost_usd=state.total_cost_usd,
    |      duration_seconds, jobs_scored, errors)
```

Note: `CostTracker` and `BaseAgent._track_cost()` perform similar logic. `BaseAgent._track_cost()` is the active path wired into `_call_llm()`. `CostTracker` provides a standalone, testable alternative with the same cost calculation logic plus a `summary()` method for aggregated reporting. Both use the same `TOKEN_PRICES` lookup.

## Configuration

All observability settings are in `Settings` (pydantic-settings, env prefix `JH_`):

### Logging Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `log_format` | `Literal["json", "console"]` | `"console"` | `"json"` for production (machine-parseable), `"console"` for development (colored, human-readable) |
| `log_level` | `str` | `"INFO"` | Standard Python log level name: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Case-insensitive. Unknown values default to `INFO`. |

### Tracing Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `otel_exporter` | `Literal["none", "console", "otlp"]` | `"none"` | `"none"` disables tracing entirely (no OTEL imports). `"console"` prints spans to stdout. `"otlp"` exports via gRPC to a collector. |
| `otel_endpoint` | `str` | `"http://localhost:4317"` | OTLP gRPC collector endpoint. Only used when `otel_exporter="otlp"`. |
| `otel_service_name` | `str` | `"job-hunter-agent"` | Service name reported in OTEL Resource. Appears in tracing backends (Jaeger, Tempo, etc.). |

### LangSmith Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `langsmith_api_key` | `SecretStr \| None` | `None` | LangSmith API key. When set, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, and `LANGCHAIN_PROJECT` env vars are configured. |
| `langsmith_project` | `str` | `"job-hunter-agent"` | LangSmith project name for trace grouping. |

### Cost Guardrail Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `max_cost_per_run_usd` | `float` | `5.0` | Hard limit. Raises `CostLimitExceededError` when accumulated cost exceeds this value. Pipeline returns partial results. |
| `warn_cost_threshold_usd` | `float` | `2.0` | Soft limit. Logs a `"cost_warning"` event when cost exceeds this threshold. Pipeline continues execution. |

### Environment Variables

All settings can be set via environment variables with `JH_` prefix:
```bash
JH_LOG_FORMAT=json
JH_LOG_LEVEL=DEBUG
JH_OTEL_EXPORTER=otlp
JH_OTEL_ENDPOINT=http://jaeger:4317
JH_OTEL_SERVICE_NAME=job-hunter-agent
JH_LANGSMITH_API_KEY=ls-xxx
JH_LANGSMITH_PROJECT=my-project
JH_MAX_COST_PER_RUN_USD=10.0
JH_WARN_COST_THRESHOLD_USD=5.0
```

## Error Handling

### Logging
- `configure_logging()` does not raise. Unknown `log_level` values default to `INFO`.
- Third-party loggers (`httpx`, `httpcore`, `sqlalchemy.engine`) are quieted to `WARNING` to prevent flooding.
- `clear_run_context()` is called in `Pipeline.run()`'s `finally` block, ensuring cleanup even on exceptions.

### Tracing
- When `_tracer is None`, all tracing functions are zero-cost no-ops: `traced_agent` passes through, `trace_pipeline_run` yields `None`, `get_tracer()` returns `None`.
- `traced_agent` re-raises exceptions after recording them on the span. It never swallows errors.
- `Pipeline._run_agent_step()` wraps span operations in `if span is not None:` guards and calls `span.end()` in a `finally` block to prevent span leaks.
- `configure_tracing_with_exporter()` uses `provider.get_tracer()` instead of `trace.get_tracer()` to avoid conflicts with `set_tracer_provider()` when called multiple times in test suites.

### Cost Tracking
- `CostTracker.record_call()` raises `CostLimitExceededError` when cost exceeds `max_cost`. The Pipeline catches this in `_run_agent_step()` and returns a partial result.
- `BaseAgent._track_cost()` performs the same check against `settings.max_cost_per_run_usd`.
- Unknown models (not in `TOKEN_PRICES`) are handled gracefully: tokens are tracked but cost stays at zero. No exception is raised.
- `extract_token_usage()` never raises: returns `(0, 0)` for any missing attribute in the response chain.

## Testing

### Test Files and Markers

| File | Marker | Tests |
|------|--------|-------|
| `tests/unit/observability/test_logging.py` | `@pytest.mark.unit` | 5 tests |
| `tests/unit/observability/test_tracing.py` | `@pytest.mark.unit` | 8 tests |
| `tests/unit/observability/test_cost_tracker.py` | `@pytest.mark.unit` | 8 tests |
| `tests/unit/observability/test_run_report.py` | `@pytest.mark.unit` | 9 tests |
| `tests/integration/test_pipeline_tracing.py` | `@pytest.mark.integration` | 4 tests |

### Unit Test Details

**test_logging.py:**
- `TestConfigureLogging`:
  - `test_configure_logging_console_mode` — console mode configures without error, `structlog.get_logger()` returns usable logger
  - `test_configure_logging_json_mode` — JSON mode produces output containing `"{"` or the event name
  - `test_configure_logging_sets_level` — `log_level="WARNING"` sets root logger to `logging.WARNING`
- `TestRunContext`:
  - `test_bind_and_clear_run_context` — bind and clear run context without raising
- `TestResolveLevel`:
  - Parametrized test with 7 cases: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, `debug` (lowercase), `unknown` (defaults to INFO)

**test_tracing.py:**
- `TestConfigureTracing`:
  - `test_configure_tracing_none` — `"none"` exporter sets `_tracer = None`
  - `test_configure_tracing_console` — `"console"` exporter creates a non-None tracer (requires OTEL packages, uses `pytest.importorskip`)
- `TestTracedAgent`:
  - `test_traced_agent_noop_when_disabled` — decorated function runs normally when `_tracer is None`
  - `test_traced_agent_creates_span` — mock tracer verifies span creation with name `"agent.scorer"` and attribute `agent.name`
- `TestTracePipelineRun`:
  - `test_trace_pipeline_run_noop` — yields `None` when tracing is disabled
- `TestLangSmith`:
  - `test_langsmith_env_set_when_key_present` — verifies `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT` are set
  - `test_langsmith_env_not_set_when_no_key` — verifies env vars are not modified when key is None
- `TestTracingHelpers`:
  - `test_get_tracer_returns_none_when_disabled` — returns None when `_tracer is None`
  - `test_get_tracer_returns_tracer_when_configured` — returns non-None after `configure_tracing_with_exporter`
  - `test_disable_tracing_resets` — `disable_tracing()` sets tracer back to None
  - `test_configure_with_exporter_creates_spans` — `InMemorySpanExporter` captures a span with correct name and attributes

**test_cost_tracker.py:**
- `TestCostTracker`:
  - `test_record_call_updates_state` — 1000 input + 500 output Haiku tokens produce correct token count and cost ($0.0028)
  - `test_record_call_raises_on_cost_limit` — large token count with low max_cost raises `CostLimitExceededError`
  - `test_record_call_warns_on_threshold` — cost above warn threshold logs warning but does not raise
  - `test_record_call_unknown_model` — unknown model tracks tokens but cost stays at 0.0
  - `test_summary_empty` — empty tracker returns zeroed summary dict
  - `test_summary_with_calls` — summary with Haiku + Sonnet calls produces correct aggregation
- `TestExtractTokenUsage`:
  - `test_extract_with_raw_response` — extracts (150, 75) from `response._raw_response.usage`
  - `test_extract_no_raw_response` — returns (0, 0) when `_raw_response` is missing
  - `test_extract_no_usage` — returns (0, 0) when `usage` attribute is missing

**test_run_report.py:**
- `TestGenerateRunReport`:
  - `test_empty_spans_returns_defaults` — empty span list produces zeroed report
  - `test_root_span_attributes_extracted` — pipeline attributes (run_id, status, tokens, cost, jobs, errors) extracted from root span
  - `test_agent_spans_sorted_by_start_time` — agent steps appear in execution order
  - `test_agent_error_captured` — error attribute on agent span captured in AgentStep
  - `test_integration_mode_manifest` — integration mode uses correct component manifest
  - `test_live_mode_manifest` — live mode uses correct component manifest
- `TestFormatRunReport`:
  - `test_format_contains_sections` — formatted output contains all section headers
  - `test_format_contains_error_details` — error info appears in formatted output
  - `test_format_empty_steps` — handles report with no agent steps

### Integration Test Details

**test_pipeline_tracing.py:**

Uses `InMemorySpanExporter` via a `span_exporter` fixture that calls `configure_tracing_with_exporter()` before each test and `disable_tracing()` after.

- `test_pipeline_produces_root_and_agent_spans` — dry-run pipeline produces `"pipeline.run"` root span plus agent child spans (`agent.parse_resume`, `agent.parse_prefs`, `agent.find_companies`)
- `test_root_span_has_summary_attributes` — root span has `pipeline.run_id` and `pipeline.status` attributes
- `test_agent_spans_have_status_attributes` — all `agent.*` spans have `agent.name` and `agent.status` attributes
- `test_tracing_disabled_produces_no_spans` — pipeline with tracing disabled produces zero spans in a fresh `InMemorySpanExporter`

**pipeline_tracing fixture (`tests/integration/conftest.py`):**

Used by `test_pipeline_dryrun.py` and `test_pipeline_real_scraping.py` to enable OTEL tracing with `InMemorySpanExporter` and auto-generate a run report after each test. Auto-detects mock mode by checking `request.fixturenames` for `integration_patches` or `dry_run_patches`.

### How to Run
```bash
uv run pytest tests/unit/observability/ -v              # All unit tests
uv run pytest tests/unit/observability/test_logging.py -v
uv run pytest tests/unit/observability/test_tracing.py -v
uv run pytest tests/unit/observability/test_cost_tracker.py -v
uv run pytest tests/integration/test_pipeline_tracing.py -v  # Requires OTEL packages
```

## Common Modification Patterns

### Add tracing to a new component

1. Import `get_tracer` from `job_hunter_agents.observability`:
   ```python
   from job_hunter_agents.observability import get_tracer
   ```
2. Create a span around the operation:
   ```python
   tracer = get_tracer()
   span = tracer.start_span("component.operation") if tracer else None
   try:
       # ... your operation ...
       if span:
           span.set_attribute("component.result_count", len(results))
           span.set_attribute("agent.status", "ok")
   except Exception as exc:
       if span:
           span.set_attribute("agent.status", "error")
           span.set_attribute("agent.error", str(exc))
       raise
   finally:
       if span:
           span.end()
   ```
3. Alternatively, use the `traced_agent` decorator for async functions:
   ```python
   from job_hunter_agents.observability import traced_agent

   @traced_agent("my_component")
   async def my_operation(...) -> ...:
       ...
   ```
4. Add a test using `InMemorySpanExporter` (see `test_configure_with_exporter_creates_spans` for pattern).

### Add cost tracking for a new LLM model

1. Add the model's pricing to `TOKEN_PRICES` in `src/job_hunter_core/constants.py`:
   ```python
   TOKEN_PRICES["claude-opus-4-20250514"] = {"input": 15.00, "output": 75.00}
   ```
   Prices are in USD per 1 million tokens.
2. Both `CostTracker.record_call()` and `BaseAgent._track_cost()` will automatically pick up the new model via the `TOKEN_PRICES.get(model)` lookup.
3. Add the model ID as a Settings field if it should be configurable:
   ```python
   opus_model: str = Field(default="claude-opus-4-20250514", description="...")
   ```
4. Update tests in `test_cost_tracker.py` to include the new model in `test_summary_with_calls`.

### Change log output format

1. The two built-in formats are `"json"` and `"console"`, selected via `settings.log_format`.
2. To add a new format (e.g., `"logfmt"`):
   - Add the literal to the `log_format` type in `Settings`: `Literal["json", "console", "logfmt"]`
   - Add a new `elif` branch in `configure_logging()` after the JSON/console selection:
     ```python
     elif settings.log_format == "logfmt":
         renderer = structlog.processors.LogfmtRenderer()
     ```
3. To change the shared processors (e.g., add a custom processor), modify the `shared_processors` list in `configure_logging()`.
4. To change which third-party loggers are quieted, modify the `for name in (...)` loop at the end of `configure_logging()`.

### Add a new context variable to all log entries

1. In the code that starts the operation, call `bind_contextvars`:
   ```python
   from structlog.contextvars import bind_contextvars
   bind_contextvars(user_id=user_id, session_id=session_id)
   ```
2. All subsequent `structlog.get_logger()` calls will include those keys.
3. Clear them when the operation ends using `clear_contextvars()` or by calling `clear_run_context()`.

### Integrate a new tracing backend

1. For OTEL-compatible backends (Jaeger, Tempo, Datadog), set `otel_exporter=otlp` and point `otel_endpoint` to the collector. No code changes needed.
2. For a custom exporter, add a new `elif` branch in `configure_tracing()`:
   ```python
   elif settings.otel_exporter == "custom":
       from my_exporter import CustomExporter
       provider.add_span_processor(BatchSpanProcessor(CustomExporter()))
   ```
3. Update the `otel_exporter` Literal type in Settings to include the new option.

## Cross-References

- **SPEC_01** (Core Models) — `PipelineState.total_tokens`, `PipelineState.total_cost_usd` are the accumulation targets for cost tracking
- **SPEC_09** (Scoring and Output) — agents call `_call_llm()` which triggers `extract_token_usage()` and `_track_cost()` on every LLM call
- **Pipeline orchestrator** (`src/job_hunter_agents/orchestrator/pipeline.py`) — wires all three observability subsystems: binds/clears run context, creates root + agent spans, logs cost summary
- **BaseAgent** (`src/job_hunter_agents/agents/base.py`) — `_call_llm()` calls `extract_token_usage()` and `_track_cost()` for every LLM call; `_log_start()`/`_log_end()` emit structured agent lifecycle events
- **Settings** (`src/job_hunter_core/config/settings.py`) — all observability configuration fields
- **Constants** (`src/job_hunter_core/constants.py`) — `TOKEN_PRICES` dict consumed by both cost tracking paths
