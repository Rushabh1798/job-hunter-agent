# Job Hunter Agent

An autonomous multi-agent system that discovers relevant job openings for you. Give it your resume and job preferences — it finds target companies, scrapes their career pages, scores every job against your profile using LLM reasoning, and outputs a ranked report with fit scores, gap analysis, and apply links.

## Features

- **8-agent pipeline** — resume parsing, preference extraction, company discovery, career page scraping, job normalization, LLM-powered scoring, report aggregation, email notification
- **ATS-aware scraping** — native API clients for Greenhouse, Lever, Ashby, and Workday; falls back to crawl4ai for custom career pages
- **LLM scoring with fit reports** — each job gets a 0-100 score with skill overlap, skill gaps, seniority match, location match, and a written recommendation
- **Lite mode** — runs with SQLite and local embeddings, zero Docker dependencies (`--lite`)
- **Full mode** — PostgreSQL with pgvector for vector search, Redis for caching
- **Crash recovery** — JSON checkpoint files after each pipeline step; resume interrupted runs with `--resume-from`
- **Cost guardrails** — configurable per-run spend limit with automatic stop
- **Dry-run mode** — mocks all external services (LLM, search, scraping, email) for safe testing with `--dry-run`
- **OpenTelemetry tracing** — per-agent spans with cost/token attributes; visualize in Jaeger with `--trace`

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- API keys: [Anthropic](https://console.anthropic.com/) + [Tavily](https://tavily.com/)
- Docker (optional, for full mode with Postgres + Redis)

## Quick Start

### Install

```bash
git clone https://github.com/rushabhthakkar/job-hunter-agent.git
cd job-hunter-agent
make install
cp .env.example .env   # add your API keys
```

### Run (Lite Mode)

No Docker needed. Uses SQLite and local embeddings:

```bash
make run-lite ARGS='resume.pdf --prefs "Senior backend engineer, Python, remote US, 150k+"'
```

### Run (Full Mode)

Requires Docker for Postgres + Redis:

```bash
make dev                # start postgres + redis
make run ARGS='resume.pdf --prefs "Senior backend engineer, Python, remote US, 150k+"'
```

### Run with Tracing

Visualize the full pipeline execution in Jaeger:

```bash
make dev-trace          # start postgres + redis + Jaeger
make run-trace ARGS='resume.pdf --prefs "Senior backend engineer, Python, remote US, 150k+"'
# Open http://localhost:16686 to see traces in Jaeger UI
```

### Run (Docker)

```bash
make docker-build
# Place resume.pdf in data/ directory
make docker-run ARGS='--prefs "Senior backend engineer, Python, remote US, 150k+"'
```

## Pipeline

```
1. ResumeParserAgent      — extracts structured profile from PDF (skills, experience, education)
2. PrefsParserAgent       — parses freeform preferences into structured search criteria
3. CompanyFinderAgent     — discovers target companies via web search + ATS detection
4. JobsScraperAgent       — scrapes career pages using ATS APIs or crawl4ai
5. JobProcessorAgent      — normalizes raw jobs, generates embeddings, deduplicates
6. JobsScorerAgent        — scores each job against candidate profile with LLM reasoning
7. AggregatorAgent        — produces ranked CSV/Excel report with scores and fit reports
8. NotifierAgent          — emails results to candidate (optional)
```

## Configuration

Key environment variables (see [`.env.example`](.env.example) for the full list):

| Variable | Required | Description |
|----------|----------|-------------|
| `JH_ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude |
| `JH_TAVILY_API_KEY` | Yes | Tavily API key for web search |
| `JH_DB_BACKEND` | No | `sqlite` (default) or `postgres` |
| `JH_MAX_COST_PER_RUN_USD` | No | Per-run cost limit (default: $5.00) |
| `JH_EMAIL_PROVIDER` | No | `smtp` or `sendgrid` (for email notifications) |
| `JH_OTEL_EXPORTER` | No | `none` (default), `console`, or `otlp` |
| `JH_OTEL_ENDPOINT` | No | OTLP endpoint (default: `http://localhost:4317`) |

## CLI Reference

```
job-hunter run <resume.pdf> [OPTIONS]

Arguments:
  resume              Path to resume PDF

Options:
  --prefs TEXT        Freeform job preferences text
  --prefs-file PATH   File containing preferences text
  --dry-run           Mock all external services, generate files only
  --trace             Enable OTLP tracing (send spans to Jaeger)
  --lite              SQLite + local embeddings, no Docker
  --company-limit N   Cap number of companies to search
  --force-rescrape    Ignore scrape cache
  --resume-from ID    Resume from a previous run's checkpoint
  -v, --verbose       Enable debug logging
```

## Project Structure

```
src/
├── job_hunter_core/       # Domain models, config, interfaces (no deps)
├── job_hunter_infra/      # DB repositories, cache, vector similarity
├── job_hunter_agents/     # Agents, tools, pipeline, prompts, observability
└── job_hunter_cli/        # Typer CLI entrypoint

tests/
├── unit/                  # Fast, fully mocked (pytest -m unit)
├── integration/           # Real DB + cache, mocked externals (pytest -m integration)
├── e2e/                   # Full pipeline with real APIs (pytest -m live)
├── fixtures/              # Sample PDFs, LLM responses, ATS responses, HTML
└── mocks/                 # Named fake implementations (tools, LLM, settings)
```

## Development

```bash
make install       # install deps + Playwright
make lint          # ruff check + mypy
make test          # unit tests
make test-int      # start infra + run integration tests
make test-e2e      # run e2e + live tests
make format        # auto-format with ruff
make dev           # start Postgres + Redis
make dev-trace     # start Postgres + Redis + Jaeger
make dev-down      # stop infrastructure
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch naming, commit conventions, architecture rules, and checklists for adding ATS clients or agents.

## License

[Apache License 2.0](LICENSE)
