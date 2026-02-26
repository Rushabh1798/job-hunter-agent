# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Temporal workflow orchestration as alternative to sequential pipeline (`--temporal` CLI flag)
- `TemporalOrchestrator` with embedded worker mode for single-process deployment
- `JobHuntWorkflow` with per-activity retry policies, task queue routing, parallel company scraping
- Temporal activities wrapping all 8 pipeline agents with token/cost delta tracking
- Pydantic v2 data converter for correct Temporal serialization/deserialization
- `TemporalConnectionError` exception with CLI error handling (no silent fallback)
- Docker Compose `temporal` profile with `temporalio/auto-setup` service
- Temporal as CI service container with E2E dry-run validation
- `PipelineState.run_result` checkpoint serialization for output file persistence across Temporal roundtrips
- `asyncio.gather(return_exceptions=True)` for resilient parallel company scraping
- Comprehensive Temporal unit tests: orchestrator, workflow, activities, embedded worker mode, queue dedup
- Integration tests for Temporal pipeline (full pipeline, output files, cost tracking, CLI flag)
- Pipeline OTEL tracing: root span + per-agent child spans with cost/error/token attributes
- Tracing helpers: `get_tracer()`, `configure_tracing_with_exporter()`, `disable_tracing()`
- CLI `--trace` flag for OTLP tracing to Jaeger
- Jaeger all-in-one in docker-compose under `trace` profile
- Makefile targets: `dev-trace` (infra + Jaeger), `run-trace` (CLI with tracing)
- OTEL section in `.env.example`
- Integration tests for pipeline tracing with InMemorySpanExporter
- Unit tests for tracing helper functions
- Integration test suite with dry-run pipeline tests, DB repository tests, Redis cache tests, checkpoint persistence tests, CLI dry-run tests
- E2E live test suite for real API validation with cost guardrails
- Fixture data files (sample resume PDF, LLM responses, ATS responses, HTML, search results)
- Named fake tool implementations (FakePDFParser, FakeWebSearchTool, FakeWebScraper, fake ATS clients, FakeEmailSender, FakeEmbedder)
- FakeLLMDispatcher that routes _call_llm calls to fixture JSON by response_model class
- Dry-run wire-up module (`dryrun.py`) with `activate_dry_run_patches()` shared by tests and CLI
- CLI `--dry-run` now mocks all external services (LLM, search, scraping, email), not just email
- Makefile targets: `test-e2e`, `test-live`
- pytest marker: `e2e` for full end-to-end pipeline tests
- README.md with features, quick start, pipeline overview, CLI reference, project structure
- GitHub Actions CI pipeline (lint, test with coverage, Docker build)
- Pre-commit hooks (trailing whitespace, EOF fixer, YAML check, ruff lint + format)
- CONTRIBUTING.md with setup, workflow, architecture rules, ATS/agent checklists
- SECURITY.md with vulnerability reporting policy and scope
- GitHub issue templates (bug report, ATS support request)
- Initial project scaffold with monorepo structure
- CLAUDE.md and PLAN.md for project planning
