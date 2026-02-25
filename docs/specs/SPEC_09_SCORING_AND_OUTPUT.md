# SPEC_09: Scoring and Output

## Purpose

This spec covers the final four agents in the pipeline: **JobProcessorAgent**, **JobsScorerAgent**, **AggregatorAgent**, and **NotifierAgent**. Together they normalize raw scraped data into structured records, score each job against the candidate profile using LLM reasoning, generate ranked CSV/Excel output files, and optionally email results. These agents transform raw pipeline data into the user-facing deliverable.

## Key Files

| File | Role |
|------|------|
| `src/job_hunter_agents/agents/job_processor.py` | Normalizes `RawJob` records into `NormalizedJob` via JSON mapping or LLM extraction |
| `src/job_hunter_agents/agents/jobs_scorer.py` | Scores `NormalizedJob` records against candidate profile in LLM batches |
| `src/job_hunter_agents/agents/aggregator.py` | Generates CSV and Excel output files from scored jobs |
| `src/job_hunter_agents/agents/notifier.py` | Sends results email with top jobs table and Excel attachment |
| `src/job_hunter_agents/prompts/job_processor.py` | Prompt templates for HTML-to-structured-data extraction |
| `src/job_hunter_agents/prompts/job_scorer.py` | Prompt templates for candidate-job fit scoring |
| `src/job_hunter_agents/agents/base.py` | `BaseAgent` ABC with `_call_llm`, `_track_cost`, `_record_error` |
| `src/job_hunter_agents/tools/email_sender.py` | `EmailSender` class — SMTP and SendGrid delivery |
| `src/job_hunter_core/models/job.py` | `RawJob`, `NormalizedJob`, `FitReport`, `ScoredJob` domain models |
| `src/job_hunter_core/constants.py` | `TOKEN_PRICES`, `SCORING_WEIGHTS` |
| `tests/unit/agents/test_job_processor.py` | Unit tests for JobProcessorAgent |
| `tests/unit/agents/test_jobs_scorer.py` | Unit tests for JobsScorerAgent |
| `tests/unit/agents/test_aggregator.py` | Unit tests for AggregatorAgent |
| `tests/unit/agents/test_notifier.py` | Unit tests for NotifierAgent |

## Public API

### JobProcessorAgent

```python
class ExtractedJob(BaseModel):
    """LLM-extracted job fields from raw HTML content."""
    title: str
    jd_text: str
    location: str | None = None
    remote_type: str = "unknown"
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str | None = None
    required_skills: list[str] = []
    preferred_skills: list[str] = []
    required_experience_years: float | None = None
    seniority_level: str | None = None
    department: str | None = None

class JobProcessorAgent(BaseAgent):
    agent_name = "job_processor"

    async def run(self, state: PipelineState) -> PipelineState:
        """Process all raw jobs into normalized jobs.

        Iterates state.raw_jobs, dispatching each to either
        _process_from_json (ATS API data) or _process_from_html (LLM extraction).
        Deduplicates by content_hash using a seen_hashes set.
        Errors per-job are recorded via _record_error, not raised.
        Results written to state.normalized_jobs.
        """

    async def _process_job(self, raw_job: RawJob) -> NormalizedJob | None:
        """Route to JSON or HTML processing based on available data."""

    def _process_from_json(self, raw_job: RawJob) -> NormalizedJob | None:
        """Direct field mapping from ATS JSON — no LLM call.

        Extracts: title from raw_json["title"], jd_text from raw_json["content"]
        or raw_json["description"], location from raw_json["location"]["name"],
        apply_url from raw_json["absolute_url"] or raw_json["applyUrl"].
        Returns None if title or jd_text is empty.
        """

    async def _process_from_html(self, raw_job: RawJob) -> NormalizedJob | None:
        """Use LLM (Haiku) to extract structured fields from raw HTML.

        Truncates raw_content to 8000 chars before sending to LLM.
        Uses instructor to parse response into ExtractedJob model.
        Logs warning for content < 100 chars.
        """

    def _compute_hash(self, company_name: str, title: str, jd_text: str) -> str:
        """SHA-256 hash of '{company_name}|{title}|{jd_text[:500]}'.

        Used for deduplication across raw jobs.
        """
```

### JobsScorerAgent

```python
BATCH_SIZE = 5  # Module-level constant: jobs scored per LLM call

class JobScore(BaseModel):
    """Single job scoring result from LLM."""
    job_index: int          # Index in the batch (0-based)
    score: int              # 0-100 overall fit score
    skill_overlap: list[str] = []
    skill_gaps: list[str] = []
    seniority_match: bool = True
    location_match: bool = True
    org_type_match: bool = True
    summary: str            # 2-3 sentence fit assessment
    recommendation: str     # "strong_match"|"good_match"|"stretch"|"mismatch"
    confidence: float = 0.8 # 0.0-1.0

class BatchScoreResult(BaseModel):
    """Batch scoring result from LLM."""
    scores: list[JobScore]

class JobsScorerAgent(BaseAgent):
    agent_name = "jobs_scorer"

    async def run(self, state: PipelineState) -> PipelineState:
        """Score all normalized jobs in batches of BATCH_SIZE.

        Returns early (no-op) if state.profile or state.preferences is None.
        After scoring:
          1. Sort by score descending
          2. Filter by settings.min_score_threshold
          3. Assign sequential ranks (1-based)
        Results written to state.scored_jobs.
        """

    async def _score_batch(
        self, jobs: list[NormalizedJob], state: PipelineState,
    ) -> list[ScoredJob]:
        """Score a batch via LLM (Sonnet model).

        Formats candidate profile + jobs block into JOB_SCORER_USER prompt.
        Parses LLM response into BatchScoreResult.
        Maps each JobScore to a ScoredJob with FitReport.
        Invalid recommendation values default to "stretch".
        Out-of-range job_index values are silently skipped.
        """

    def _format_jobs_block(self, jobs: list[NormalizedJob]) -> str:
        """Format jobs as XML-tagged blocks for the scoring prompt.

        Each job wrapped in <job index="N"> tags containing:
        Company, Title, Location, Remote, Salary, Required Skills,
        Preferred Skills, Experience, Seniority, Description (truncated to 1000 chars).
        """
```

### AggregatorAgent

```python
class AggregatorAgent(BaseAgent):
    agent_name = "aggregator"

    async def run(self, state: PipelineState) -> PipelineState:
        """Write scored jobs to output files.

        Creates output_dir if it doesn't exist.
        Checks state.config.output_formats for "csv" and/or "xlsx".
        File naming: {run_id}_results.csv / {run_id}_results.xlsx.
        Builds state.run_result via state.build_result().
        Status is "success" if scored_jobs is non-empty, "partial" otherwise.
        """

    def _build_rows(self, state: PipelineState) -> list[dict[str, object]]:
        """Build output rows from scored jobs.

        Output columns (in order):
          Rank, Score, Recommendation, Company, Title, Location,
          Remote Type, Posted Date, Salary Range, Skill Match,
          Skill Gaps, Fit Summary, Apply URL
        """

    def _write_csv(self, rows: list[dict[str, object]], path: Path) -> None:
        """Write rows to CSV using csv.DictWriter. No-op if rows is empty."""

    def _write_excel(
        self, rows: list[dict[str, object]], path: Path, state: PipelineState,
    ) -> None:
        """Write rows to Excel with formatting. No-op if rows is empty.

        Features:
        - "Results" sheet with data from pandas DataFrame
        - Conditional fill on Score column: green (#C6EFCE) for >= 80,
          yellow (#FFEB9C) for >= 60
        - Apply URL column (col 13/M) hyperlinked with blue underlined font
        - "Run Summary" sheet with:
          Run ID, Companies Attempted, Jobs Scraped, Jobs Scored,
          Total Tokens, Estimated Cost (USD), Errors
        """
```

### NotifierAgent

```python
EMAIL_HTML_TEMPLATE: str  # Module-level HTML template with placeholders
EMAIL_TEXT_TEMPLATE: str  # Module-level plaintext template with placeholders

class NotifierAgent(BaseAgent):
    agent_name = "notifier"

    async def run(self, state: PipelineState) -> PipelineState:
        """Send email with results.

        Skips entirely (no-op) when:
          - state.config.dry_run is True
          - state.profile is None
          - state.run_result is None
        On success, sets state.run_result.email_sent = True.
        On failure, records error but does not raise.
        """

    async def _send_email(self, state: PipelineState) -> bool:
        """Build and send the results email.

        Subject: "[Job Hunter] {count} new matches for {title} - {date}"
        Body: Top 5 scored jobs in an HTML table + plaintext fallback.
        Attachment: First .xlsx file from state.run_result.output_files.
        Constructs EmailSender with settings for provider, SMTP, SendGrid.
        """
```

## Prompt Templates

### Job Processor — `src/job_hunter_agents/prompts/job_processor.py`

**JOB_PROCESSOR_SYSTEM** (system prompt):
```
You are a job listing parser. Extract structured job information from raw HTML or
text content of job postings.

<rules>
- Extract the exact job title as written
- Parse salary ranges if mentioned (convert to integers, USD)
- Identify remote_type from location and description: "remote", "hybrid", "onsite", "unknown"
- Extract required vs preferred skills separately
- Do NOT infer posted_date - only extract if explicitly stated
- If salary is in a non-USD currency, note the currency code
- For seniority_level, infer from title and requirements
</rules>
```

**JOB_PROCESSOR_USER** (user prompt):
```
<company_name>{company_name}</company_name>
<source_url>{source_url}</source_url>

<raw_content>
{raw_content}
</raw_content>

Parse this job posting and extract all structured fields.
```

Placeholder variables:
- `{company_name}` — `raw_job.company_name`
- `{source_url}` — `str(raw_job.source_url)`
- `{raw_content}` — `content[:8000]` (truncated raw HTML)

Note: `JOB_PROCESSOR_SYSTEM` is defined but not currently passed to `_call_llm` in the agent. The user prompt is self-contained.

### Job Scorer — `src/job_hunter_agents/prompts/job_scorer.py`

**JOB_SCORER_SYSTEM** (system prompt):
```
You are a job-candidate fit evaluator. Score how well each job matches the candidate.

<scoring_dimensions>
- skill_match (30%): Overlap between candidate skills and job requirements
- seniority (20%): Match between candidate level and job level
- location (15%): Geographic/remote compatibility
- org_type (15%): Organization type preference match
- growth_stage (10%): Company stage alignment
- compensation_fit (10%): Salary range alignment (if known)
</scoring_dimensions>

<calibration>
- A score of 85+ ("strong match") should be RARE
- 70-84 is a "good match"
- 60-69 is "worth considering"
- Below 60 is "weak match"
- Be honest about gaps. Do not inflate scores.
</calibration>

<rules>
- Think through each dimension before scoring
- Consider both required AND preferred skills
- Location mismatch with no remote option is a significant penalty
- Missing years of experience is a moderate penalty
- "Nice to have" skill gaps are minor penalties
</rules>
```

**JOB_SCORER_USER** (user prompt):
```
<candidate>
Name: {name}
Title: {current_title}
Years of Experience: {years_of_experience}
Seniority: {seniority_level}
Skills: {skills}
Industries: {industries}
Location: {location}
Remote Preference: {remote_preference}
Preferred Org Types: {org_types}
Salary Range: {salary_range}
</candidate>

<jobs>
{jobs_block}
</jobs>

For each job, provide a detailed FitReport with:
- score (0-100)
- skill_overlap (matched skills)
- skill_gaps (missing required skills)
- seniority_match, location_match, org_type_match (booleans)
- summary (2-3 sentence fit assessment)
- recommendation: "strong_match", "good_match", "worth_considering", or "weak_match"
- confidence (0.0-1.0)

<thinking>
Reason through each dimension for each job before outputting scores.
</thinking>
```

Placeholder variables:
- `{name}` — `profile.name`
- `{current_title}` — `profile.current_title or "Not specified"`
- `{years_of_experience}` — `profile.years_of_experience`
- `{seniority_level}` — `profile.seniority_level or "Not specified"`
- `{skills}` — comma-joined `s.name for s in profile.skills`
- `{industries}` — comma-joined `profile.industries` or `"Not specified"`
- `{location}` — `profile.location or "Not specified"`
- `{remote_preference}` — `prefs.remote_preference`
- `{org_types}` — comma-joined `prefs.org_types`
- `{salary_range}` — formatted from `prefs.min_salary`/`prefs.max_salary` or `"Not specified"`
- `{jobs_block}` — output of `_format_jobs_block()`, XML-tagged job entries

## Internal Dependencies

- **`job_hunter_agents.agents.base.BaseAgent`** — `_call_llm()` for LLM calls with instructor, `_track_cost()` for token/cost accounting, `_record_error()` for error recording, `_log_start()`/`_log_end()` for structured logging
- **`job_hunter_core.models.job`** — `RawJob`, `NormalizedJob`, `FitReport`, `ScoredJob` domain models
- **`job_hunter_core.models.candidate`** — `CandidateProfile`, `SearchPreferences`, `Skill` (used by scorer to format prompt)
- **`job_hunter_core.models.run`** — `RunConfig` (for `output_formats`, `run_id`, `dry_run`), `RunResult` (built by aggregator)
- **`job_hunter_core.state.PipelineState`** — mutable state carrying `raw_jobs`, `normalized_jobs`, `scored_jobs`, `profile`, `preferences`, `errors`, `total_tokens`, `total_cost_usd`, `run_result`
- **`job_hunter_core.constants.TOKEN_PRICES`** — pricing table for cost tracking in `BaseAgent._track_cost()`
- **`job_hunter_core.exceptions`** — `CostLimitExceededError` (raised by `_track_cost`), `EmailDeliveryError` (raised by `EmailSender`)
- **`job_hunter_agents.prompts.job_processor`** — `JOB_PROCESSOR_USER` template
- **`job_hunter_agents.prompts.job_scorer`** — `JOB_SCORER_USER` template
- **`job_hunter_agents.tools.email_sender.EmailSender`** — instantiated by NotifierAgent with settings-derived config

## External Dependencies

| Package | Used By | Purpose |
|---------|---------|---------|
| `anthropic` + `instructor` | BaseAgent._call_llm | Structured LLM output via Claude API |
| `pydantic` | ExtractedJob, JobScore, BatchScoreResult | Response model schemas for instructor |
| `tenacity` | BaseAgent._call_llm | Retry with exponential backoff (max 3 attempts, 1-10s wait) |
| `pandas` | AggregatorAgent._write_excel | DataFrame creation for Excel export |
| `openpyxl` | AggregatorAgent._write_excel | Excel formatting (conditional fills, hyperlinks, multi-sheet) |
| `csv` (stdlib) | AggregatorAgent._write_csv | CSV file writing |
| `hashlib` (stdlib) | JobProcessorAgent._compute_hash | SHA-256 content deduplication |
| `aiosmtplib` | EmailSender._send_smtp | Async SMTP email delivery |
| `sendgrid` | EmailSender._send_sendgrid | SendGrid API email delivery |
| `structlog` | All agents | Structured logging |

## Data Flow

```
state.raw_jobs (from JobsScraperAgent)
    |
    v
JobProcessorAgent.run()
    |-- For each RawJob:
    |     |-- raw_json present? -> _process_from_json() [no LLM, direct mapping]
    |     |-- raw_html present? -> _process_from_html() [LLM: Haiku + ExtractedJob]
    |     |-- neither?          -> skip (returns None)
    |-- Deduplicate by content_hash (SHA-256 of company|title|jd[:500])
    |-- Append unique results to state.normalized_jobs
    v
state.normalized_jobs
    |
    v
JobsScorerAgent.run()
    |-- Guard: returns early if profile or preferences is None
    |-- Batch into groups of BATCH_SIZE (5)
    |-- For each batch:
    |     |-- Format candidate profile + jobs_block
    |     |-- LLM call: Sonnet + BatchScoreResult response model
    |     |-- Map each JobScore -> FitReport -> ScoredJob
    |-- Sort all scored jobs by score descending
    |-- Filter: keep only score >= settings.min_score_threshold
    |-- Assign sequential ranks (1-based)
    v
state.scored_jobs
    |
    v
AggregatorAgent.run()
    |-- _build_rows(): scored_jobs -> list of column dicts
    |-- If "csv" in output_formats: _write_csv()
    |-- If "xlsx" in output_formats: _write_excel()
    |     |-- Results sheet with conditional formatting
    |     |-- Run Summary sheet with pipeline metrics
    |-- Build state.run_result via state.build_result()
    v
state.run_result + output files on disk
    |
    v
NotifierAgent.run()
    |-- Guard: skip if dry_run, missing profile, or missing run_result
    |-- Build email subject with count + title + date
    |-- Build HTML body with top 5 jobs table
    |-- Build plaintext body fallback
    |-- Find .xlsx attachment from run_result.output_files
    |-- Construct EmailSender with settings
    |-- EmailSender.send() -> SMTP or SendGrid
    |-- Set state.run_result.email_sent = True on success
    v
Email delivered (or error recorded)
```

## Configuration

All settings flow from `Settings` (pydantic-settings) via `BaseAgent.settings`:

| Setting | Type | Default | Used By |
|---------|------|---------|---------|
| `min_score_threshold` | `int` | `60` | JobsScorerAgent — filter out jobs below this score |
| `top_k_semantic` | `int` | `50` | Shortlist size for semantic search (upstream, not in these agents) |
| `max_jobs_per_company` | `int` | `10` | Maximum jobs to process per company (upstream limit) |
| `output_dir` | `Path` | `./output` | AggregatorAgent — directory for CSV/Excel files |
| `haiku_model` | `str` | `claude-haiku-4-5-20251001` | JobProcessorAgent — model for HTML extraction |
| `sonnet_model` | `str` | `claude-sonnet-4-5-20250514` | JobsScorerAgent — model for scoring |
| `max_cost_per_run_usd` | `float` | `5.0` | BaseAgent._track_cost — hard stop on cost |
| `warn_cost_threshold_usd` | `float` | `2.0` | BaseAgent._track_cost — log warning threshold |
| `email_provider` | `Literal["sendgrid", "smtp"]` | `"smtp"` | NotifierAgent — email delivery method |
| `smtp_host` | `str` | `"smtp.gmail.com"` | NotifierAgent — SMTP server |
| `smtp_port` | `int` | `587` | NotifierAgent — SMTP port |
| `smtp_user` | `str` | `""` | NotifierAgent — SMTP username and From address |
| `smtp_password` | `SecretStr \| None` | `None` | NotifierAgent — SMTP password |
| `sendgrid_api_key` | `SecretStr \| None` | `None` | NotifierAgent — SendGrid API key |

`RunConfig` fields used:
- `run_id` — file naming (`{run_id}_results.csv`), email subject, run summary
- `output_formats` — `list[str]`, default `["xlsx", "csv"]`, checked by AggregatorAgent
- `dry_run` — NotifierAgent skips email when `True`

## Error Handling

### JobProcessorAgent
- Per-job errors are caught by the outer `try/except` in `run()` and recorded via `self._record_error(state, e, company_name=..., job_id=...)`. The agent continues processing remaining jobs.
- Returns `None` for jobs with no `raw_json` or `raw_html`, silently skipping them.
- Logs a `"low_quality_content"` warning for HTML content under 100 characters.

### JobsScorerAgent
- Per-batch errors are caught and recorded via `self._record_error(state, e)`. Other batches continue.
- Returns early (no scoring) if `state.profile` or `state.preferences` is `None`.
- Invalid `recommendation` values from the LLM are normalized to `"stretch"`.
- Out-of-range `job_index` values from the LLM are silently skipped (the `0 <= idx < len(jobs)` guard).

### AggregatorAgent
- `_write_csv` and `_write_excel` are no-ops when `rows` is empty, preventing empty file creation.
- Sets `run_result.status = "partial"` when `scored_jobs` is empty, `"success"` otherwise.
- Directory creation uses `mkdir(parents=True, exist_ok=True)`.

### NotifierAgent
- Email send failures are caught by the outer `try/except` and recorded via `_record_error`. The pipeline does not crash.
- `EmailSender.send()` wraps all provider-specific exceptions into `EmailDeliveryError`.
- Skips cleanly on `dry_run`, missing `profile`, or missing `run_result`.

### Cost Guardrail (via BaseAgent._track_cost)
- If accumulated `state.total_cost_usd` exceeds `settings.max_cost_per_run_usd`, raises `CostLimitExceededError`, which the Pipeline catches and returns a partial result.
- Logs a warning when cost exceeds `settings.warn_cost_threshold_usd`.

## Testing

### Test Files
- `tests/unit/agents/test_job_processor.py` — 4 tests
- `tests/unit/agents/test_jobs_scorer.py` — 4 tests
- `tests/unit/agents/test_aggregator.py` — 4 tests
- `tests/unit/agents/test_notifier.py` — 3 tests

### Test Strategy
All tests are `@pytest.mark.unit`. LLM calls are mocked at the `_call_llm` level or via `patch.object`. `AsyncAnthropic` and `instructor` are patched at import to prevent real API client creation.

### Key Test Scenarios

**JobProcessorAgent:**
- `test_process_json_job` — JSON jobs produce NormalizedJob without LLM call
- `test_deduplication_by_hash` — duplicate raw_json jobs produce single normalized job
- `test_process_error_recorded` — bad JSON (missing title) records no normalized jobs, does not raise
- `test_compute_hash_deterministic` — same inputs produce same 64-char hex hash

**JobsScorerAgent:**
- `test_scores_jobs` — scores 2 jobs, verifies descending sort and rank assignment
- `test_filters_below_threshold` — jobs below `min_score_threshold=80` are excluded
- `test_skips_without_profile` — returns empty scored_jobs when profile is None
- `test_format_jobs_block` — jobs block includes company, title, and XML index attribute

**AggregatorAgent:**
- `test_writes_csv` — CSV file is created and listed in `run_result.output_files`
- `test_writes_xlsx` — Excel file is created and listed in `run_result.output_files`
- `test_empty_scored_jobs` — empty input produces `run_result.status == "partial"`
- `test_build_rows` — row dict contains expected column keys (Rank, Score, Apply URL)

**NotifierAgent:**
- `test_dry_run_skips_email` — `dry_run=True` skips email, `email_sent` stays False
- `test_sends_email` — `EmailSender.send` is called, `email_sent` is set to True
- `test_email_failure_recorded` — SMTP error is recorded in `state.errors`, no crash

### How to Run
```bash
uv run pytest tests/unit/agents/test_job_processor.py -v
uv run pytest tests/unit/agents/test_jobs_scorer.py -v
uv run pytest tests/unit/agents/test_aggregator.py -v
uv run pytest tests/unit/agents/test_notifier.py -v
```

## Common Modification Patterns

### Modify scoring dimensions or weights

1. Edit the `<scoring_dimensions>` block in `src/job_hunter_agents/prompts/job_scorer.py` (`JOB_SCORER_SYSTEM`). Change weight percentages or add/remove dimensions.
2. Update `SCORING_WEIGHTS` in `src/job_hunter_core/constants.py` to match (used for reference/documentation, not enforced programmatically since scoring is LLM-driven).
3. If adding a new boolean dimension (like `seniority_match`), add the field to both `JobScore` in `jobs_scorer.py` and `FitReport` in `src/job_hunter_core/models/job.py`.
4. Update the `_score_batch` method to map the new field from `JobScore` to `FitReport`.
5. Update `JOB_SCORER_PROMPT_VERSION` in `src/job_hunter_core/constants.py`.
6. Update tests in `test_jobs_scorer.py` to include the new field in mock `JobScore` fixtures.

### Add a new output format

1. In `AggregatorAgent.run()`, add a new conditional block alongside the existing `"csv"` and `"xlsx"` checks:
   ```python
   if "json" in state.config.output_formats:
       json_path = output_dir / f"{state.config.run_id}_results.json"
       self._write_json(rows, json_path)
       output_files.append(str(json_path))
   ```
2. Implement `_write_json()` (or similar) as a private method on `AggregatorAgent`.
3. Update `RunConfig.output_formats` default in `src/job_hunter_core/models/run.py` if the new format should be included by default.
4. Add a test in `test_aggregator.py` mirroring `test_writes_csv`.

### Change email template

1. Edit `EMAIL_HTML_TEMPLATE` and/or `EMAIL_TEXT_TEMPLATE` at the top of `src/job_hunter_agents/agents/notifier.py`.
2. Placeholders available: `{name}`, `{total_jobs}`, `{above_threshold}`, `{top_rows}` (HTML only), `{top_text}` (text only), `{run_id}`.
3. If adding new placeholders, update `_send_email()` to pass them in the `.format()` calls.
4. To change the number of top jobs shown, modify `top_jobs = state.scored_jobs[:5]` in `_send_email()`.
5. To add new attachment types, update the attachment selection logic (currently finds first `.xlsx`).

### Add a new field to output columns

1. Add the field to the row dict in `AggregatorAgent._build_rows()`.
2. If the field comes from `FitReport`, it is accessed via `sj.fit_report.{field}`.
3. If the field comes from `NormalizedJob`, it is accessed via `sj.job.{field}`.
4. Excel column positions are implicit (left-to-right from dict order). If the new column needs formatting, update `_write_excel()` accordingly.
5. Update `test_build_rows` in `test_aggregator.py` to assert the new key exists.

## Cross-References

- **SPEC_01** (Core Models) — `RawJob`, `NormalizedJob`, `FitReport`, `ScoredJob`, `CandidateProfile`, `SearchPreferences`, `RunConfig`, `RunResult`
- **SPEC_07** (Scraping) — produces `state.raw_jobs` consumed by JobProcessorAgent
- **SPEC_10** (Observability) — `_call_llm` calls `extract_token_usage` and `_track_cost` for cost accounting; all agents use `structlog` for structured logging
- **Pipeline orchestrator** (`src/job_hunter_agents/orchestrator/pipeline.py`) — wires these four agents as steps `process_jobs`, `score_jobs`, `aggregate`, `notify` in `PIPELINE_STEPS`
