# Contributing to Job Hunter Agent

Thank you for your interest in contributing. This guide covers setup, workflow, and coding standards.

## Getting Started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (optional, needed for Postgres + Redis in full mode)

### Setup

```bash
git clone https://github.com/rushabhthakkar/job-hunter-agent.git
cd job-hunter-agent
make install
uv run pre-commit install
cp .env.example .env    # fill in API keys
make lint && make test
```

## Development Workflow

### Branch Naming

Use prefixed branches off `main`:

- `feat/add-jobvite-client`
- `fix/greenhouse-pagination`
- `docs/update-readme`
- `refactor/extract-retry-logic`

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add Jobvite ATS client
fix: handle empty job listings in Greenhouse API
test: add scorer agent edge case tests
refactor: extract retry policy from base agent
docs: update CLI reference in README
chore: bump ruff to v0.9.0
```

## Before Submitting a PR

Run these checks locally — they must all pass:

```bash
make lint     # ruff check + mypy
make test     # unit tests with coverage
```

- Coverage must remain at or above 80%.
- All existing tests must still pass.
- New code must include tests.

## Architecture Rules

### Package Dependency Direction

```
core → infra → agents → cli
```

Packages may only import from packages to their left. No circular imports.

- `job_hunter_core` — models, config, interfaces (no internal deps)
- `job_hunter_infra` — DB, cache, vector (depends on core)
- `job_hunter_agents` — agents, tools, pipeline (depends on core + infra)
- `job_hunter_cli` — CLI entrypoint (depends on all)

### Code Standards

- Complete type annotations on all functions
- Docstrings on all public functions
- No function body over 50 lines
- No file over 300 lines
- Use `structlog` for logging (no `print()`)
- No bare `except:` — catch specific exceptions
- Use `datetime.now(UTC)` not `datetime.utcnow()`

## Adding a New ATS Client

1. Create `src/job_hunter_agents/tools/ats_clients/<ats_name>.py`
2. Implement `BaseATSClient` from `ats_clients/base.py` (methods: `detect`, `fetch_jobs`)
3. Register the client in `ats_clients/__init__.py`
4. Add the ATS type to `ATSType` enum in `src/job_hunter_core/models/company.py`
5. Add tests in `tests/unit/tools/test_ats_clients.py` with fixture JSON responses

## Adding a New Agent

1. Create `src/job_hunter_agents/agents/<agent_name>.py`
2. Extend `BaseAgent` from `agents/base.py` (implement `run` method)
3. Add the agent step to `Pipeline` in `orchestrator/pipeline.py`
4. Add a prompt template in `prompts/<agent_name>.py` if the agent uses LLM calls
5. Add tests in `tests/unit/agents/test_<agent_name>.py`

## Reporting Issues

- **Bugs:** Use the [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md) template
- **New ATS support:** Use the [ATS Support Request](.github/ISSUE_TEMPLATE/ats_support_request.md) template
- **Security vulnerabilities:** See [SECURITY.md](SECURITY.md) — do not open public issues

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
