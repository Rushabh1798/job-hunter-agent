# SPEC_INDEX: Spec File Navigation Guide

Load only the spec files you need for the current task. Most tasks require 1-2 specs.

## Quick Reference: Task -> Spec Files

### Model and Schema Changes

| Task | Load These Specs |
|------|-----------------|
| Add/modify a domain model field | SPEC_01 |
| Add a new Settings config field | SPEC_01 |
| Add a new exception type | SPEC_01 |
| Change PipelineState structure | SPEC_01, SPEC_04 |
| Add a new DB table or column | SPEC_01, SPEC_02 |
| Add/modify a repository query | SPEC_02 |
| Change cache TTL or strategy | SPEC_03 |
| Add a new domain cache type | SPEC_03 |

### Agent Development

| Task | Load These Specs |
|------|-----------------|
| Understand how agents work | SPEC_04 |
| Build a new agent from scratch | SPEC_04, SPEC_05 (for pattern) |
| Modify the pipeline step order | SPEC_04 |
| Fix checkpoint/crash recovery | SPEC_04 |
| Modify resume/prefs parsing | SPEC_05, SPEC_01 |
| Modify company discovery | SPEC_06, SPEC_08 |
| Modify job scraping | SPEC_06, SPEC_08, SPEC_07 |
| Modify job scoring/ranking | SPEC_09, SPEC_01 |
| Modify output format (CSV/Excel) | SPEC_09 |
| Modify email notifications | SPEC_09, SPEC_07 |
| Update an LLM prompt template | SPEC_05, SPEC_06, or SPEC_09 (whichever owns the agent) |

### Tool and Integration Work

| Task | Load These Specs |
|------|-----------------|
| Add a new ATS client | SPEC_08, SPEC_06, SPEC_04 (for dryrun) |
| Modify an existing ATS client | SPEC_08 |
| Fix PDF parsing | SPEC_07 |
| Fix web scraping (crawl4ai/Playwright) | SPEC_07 |
| Change embedding provider | SPEC_07, SPEC_03 |
| Fix email sending | SPEC_07 |
| Add a new external tool | SPEC_07, SPEC_04 (for dryrun) |

### Observability and Operations

| Task | Load These Specs |
|------|-----------------|
| Configure logging/tracing | SPEC_10 |
| Add cost tracking for new model | SPEC_10, SPEC_01 (TOKEN_PRICES) |
| Debug tracing issues | SPEC_10 |
| Add a new CLI flag | SPEC_11 |
| Modify Docker build | SPEC_11 |
| Fix CI pipeline | SPEC_11 |
| Add a new test mock | SPEC_11, (relevant spec) |
| Add a test fixture | SPEC_11 |
| Add dry-run support for new tool | SPEC_04, SPEC_11 |

---

## Spec File Listing

| # | Filename | Package(s) | Scope |
|---|---------|-----------|-------|
| 01 | [SPEC_01_CORE_MODELS.md](specs/SPEC_01_CORE_MODELS.md) | `job_hunter_core` | Domain models, config, interfaces, state, constants, exceptions |
| 02 | [SPEC_02_DATABASE.md](specs/SPEC_02_DATABASE.md) | `job_hunter_infra/db` | ORM models, engine/session, 5 repositories |
| 03 | [SPEC_03_CACHE_AND_VECTOR.md](specs/SPEC_03_CACHE_AND_VECTOR.md) | `job_hunter_infra/cache+vector` | Redis + DB cache, company/page caches, vector similarity |
| 04 | [SPEC_04_AGENT_FRAMEWORK.md](specs/SPEC_04_AGENT_FRAMEWORK.md) | `job_hunter_agents` | BaseAgent, Pipeline, checkpoint, dryrun |
| 05 | [SPEC_05_PARSING_AGENTS.md](specs/SPEC_05_PARSING_AGENTS.md) | `job_hunter_agents` | ResumeParser + PrefsParser agents + prompts |
| 06 | [SPEC_06_DISCOVERY_AND_SCRAPING.md](specs/SPEC_06_DISCOVERY_AND_SCRAPING.md) | `job_hunter_agents` | CompanyFinder + JobsScraper agents + prompts |
| 07 | [SPEC_07_TOOLS.md](specs/SPEC_07_TOOLS.md) | `job_hunter_agents/tools` | PDF parser, web scraper, web search, embedder, email sender |
| 08 | [SPEC_08_ATS_CLIENTS.md](specs/SPEC_08_ATS_CLIENTS.md) | `job_hunter_agents/tools/ats_clients` | BaseATSClient + 4 implementations |
| 09 | [SPEC_09_SCORING_AND_OUTPUT.md](specs/SPEC_09_SCORING_AND_OUTPUT.md) | `job_hunter_agents` | JobProcessor + JobsScorer + Aggregator + Notifier + prompts |
| 10 | [SPEC_10_OBSERVABILITY.md](specs/SPEC_10_OBSERVABILITY.md) | `job_hunter_agents/observability` | Logging, tracing, cost tracking |
| 11 | [SPEC_11_CLI_AND_DEVOPS.md](specs/SPEC_11_CLI_AND_DEVOPS.md) | `job_hunter_cli` + devops | CLI, Makefile, Docker, CI, test mocks/fixtures |

---

## Dependency Graph

```
SPEC_01 (Core Models) <── everything depends on this
    │
    ├── SPEC_02 (Database) <── SPEC_03 (db_cache imports Base)
    │       │
    │       └── SPEC_03 (Cache & Vector)
    │
    ├── SPEC_04 (Agent Framework) <── all agent specs
    │       │
    │       ├── SPEC_05 (Parsing Agents)
    │       ├── SPEC_06 (Discovery & Scraping) <── SPEC_07, SPEC_08
    │       └── SPEC_09 (Scoring & Output) <── SPEC_07
    │
    ├── SPEC_07 (Tools) ── standalone, no agent deps
    ├── SPEC_08 (ATS Clients) ── standalone, no agent deps
    ├── SPEC_10 (Observability) ── used by SPEC_04 pipeline
    └── SPEC_11 (CLI & DevOps) ── composition root, wires everything
```

**Reading order for full understanding:** SPEC_01 -> SPEC_02/03 -> SPEC_04 -> SPEC_07/08 -> SPEC_05/06/09 -> SPEC_10 -> SPEC_11
