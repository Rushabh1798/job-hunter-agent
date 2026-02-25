# SPEC_05: Parsing Agents

## Purpose

The parsing agents are the first two steps in the pipeline. They convert unstructured input (a resume PDF and freeform preferences text) into structured Pydantic models that all downstream agents consume. `ResumeParserAgent` produces a `CandidateProfile`; `PrefsParserAgent` produces `SearchPreferences`. Both extend `BaseAgent` and use the `instructor` library to get structured LLM output from Claude Haiku.

## Key Files

| File | Primary Exports | Lines |
|------|----------------|-------|
| `src/job_hunter_agents/agents/resume_parser.py` | `ResumeParserAgent` | 58 |
| `src/job_hunter_agents/agents/prefs_parser.py` | `PrefsParserAgent` | 54 |
| `src/job_hunter_agents/prompts/resume_parser.py` | `RESUME_PARSER_SYSTEM`, `RESUME_PARSER_USER` | 39 |
| `src/job_hunter_agents/prompts/prefs_parser.py` | `PREFS_PARSER_SYSTEM`, `PREFS_PARSER_USER` | 26 |
| `tests/unit/agents/test_resume_parser.py` | `TestResumeParserAgent` (2 tests) | 105 |
| `tests/unit/agents/test_prefs_parser.py` | `TestPrefsParserAgent` (2 tests) | 93 |

## Public API

### ResumeParserAgent

```python
class ResumeParserAgent(BaseAgent):
    agent_name = "resume_parser"

    async def run(self, state: PipelineState) -> PipelineState
```

**Step-by-step logic of `run()`:**

1. **Log start** -- calls `self._log_start({"resume_path": str(state.config.resume_path)})` with the resume path for observability.
2. **Extract text from PDF** -- instantiates `PDFParser()` and calls `await pdf_parser.extract_text(state.config.resume_path)`. The `PDFParser` internally tries pdfplumber, then pypdf, raising `ScannedPDFError` / `EncryptedPDFError` / `InvalidFileError` on failure. The result is the raw text string.
3. **Compute content hash** -- computes `hashlib.sha256(raw_text.encode()).hexdigest()` for cache invalidation and deduplication.
4. **Call LLM for structured extraction** -- calls `self._call_llm()` with:
   - `messages`: a single user message using the `RESUME_PARSER_USER` template, with `{resume_text}` replaced by the extracted text.
   - `model`: `self.settings.haiku_model` (default: `"claude-haiku-4-5-20251001"`).
   - `response_model`: `CandidateProfile` -- instructor validates the LLM output against the Pydantic schema.
   - `state`: passed through for cost tracking.
   - `max_retries`: `3` (explicit; the default in `_call_llm` is also 3).
5. **Patch mutable fields** -- sets `profile.raw_text = raw_text` and `profile.content_hash = content_hash`. These fields cannot be reliably extracted by the LLM (per the prompt: "Content hash will be computed separately"), so they are set programmatically.
6. **Write to state** -- `state.profile = profile`.
7. **Log end** -- calls `self._log_end()` with duration, candidate name, email, and skills count.
8. **Return state** -- returns the mutated `PipelineState`.

**Inputs required on `state`:**
- `state.config.resume_path` (Path) -- must point to an existing `.pdf` file.

**Outputs written to `state`:**
- `state.profile` (CandidateProfile) -- fully populated with LLM-extracted fields plus `raw_text` and `content_hash`.

---

### PrefsParserAgent

```python
class PrefsParserAgent(BaseAgent):
    agent_name = "prefs_parser"

    async def run(self, state: PipelineState) -> PipelineState
```

**Step-by-step logic of `run()`:**

1. **Log start** -- calls `self._log_start({"text_length": len(state.config.preferences_text)})`.
2. **Call LLM for structured extraction** -- calls `self._call_llm()` with:
   - `messages`: a single user message using the `PREFS_PARSER_USER` template, with `{preferences_text}` replaced by the raw preferences text from `state.config.preferences_text`.
   - `model`: `self.settings.haiku_model`.
   - `response_model`: `SearchPreferences`.
   - `state`: passed through for cost tracking.
   - `max_retries`: uses the `_call_llm` default of `3` (not explicitly passed).
3. **Patch raw_text** -- sets `prefs.raw_text = state.config.preferences_text` to preserve the original user input.
4. **Write to state** -- `state.preferences = prefs`.
5. **Log end** -- calls `self._log_end()` with duration, target titles, and preferred locations.
6. **Return state** -- returns the mutated `PipelineState`.

**Inputs required on `state`:**
- `state.config.preferences_text` (str) -- the freeform preferences string from the CLI.

**Outputs written to `state`:**
- `state.preferences` (SearchPreferences) -- fully populated with LLM-extracted fields plus `raw_text`.

## Prompt Templates

### Resume Parser Prompts (`prompts/resume_parser.py`)

**`RESUME_PARSER_SYSTEM`** (not currently passed to `_call_llm` -- defined but unused in the agent):

```
You are an expert resume parser. Extract structured information from resumes accurately.

<rules>
- NEVER hallucinate skills or experience not explicitly mentioned in the resume
- If a field is ambiguous, prefer conservative interpretation
- Extract ALL technical skills mentioned, including frameworks and tools
- Infer seniority_level from years of experience and titles if not stated
- For years_of_experience, calculate from earliest work date to present
- Content hash will be computed separately -- do not include it
</rules>
```

**`RESUME_PARSER_USER`** -- template variables: `{resume_text}`

```
<resume_text>
{resume_text}
</resume_text>

Parse the above resume and extract all structured information. Return the candidate
profile with all available fields populated. If a field cannot be determined from the
resume, omit it or use null.

<examples>
<example>
Input: "Jane Doe | jane@email.com | 5+ years Python/ML experience at startups"
Output should include: name="Jane Doe", email="jane@email.com", years_of_experience=5.0,
skills including Python and ML, seniority_level="mid"
</example>
<example>
Input: "Recent graduate, BSc CS 2024, internships at Google and Meta"
Output should include: years_of_experience=1.0 (internships count),
seniority_level="entry", education with degree and year
</example>
</examples>
```

**Note:** The system prompt (`RESUME_PARSER_SYSTEM`) is exported from the module but is not currently included in the `messages` list passed to `_call_llm`. The agent sends only the user message. The `instructor` library handles schema enforcement via the `response_model` parameter.

---

### Preferences Parser Prompts (`prompts/prefs_parser.py`)

**`PREFS_PARSER_SYSTEM`** (not currently passed to `_call_llm` -- defined but unused in the agent):

```
You are a preference parser for job search. Extract structured search preferences
from freeform natural language text.

<rules>
- If remote preference is not mentioned, default to "flexible"
- If salary is not mentioned, leave min_salary and max_salary as null
- Parse both explicit ("I want") and implicit ("not interested in") preferences
- For company size, map: startup -> "startup", mid-size -> "mid", large/enterprise -> "large"
- "Big tech" = excluded_companies pattern, not a company size
- Always use USD for currency unless explicitly stated otherwise
</rules>
```

**`PREFS_PARSER_USER`** -- template variables: `{preferences_text}`

```
<preferences_text>
{preferences_text}
</preferences_text>

Parse the above free-form job search preferences into structured fields.
```

**Note:** Same pattern as the resume parser -- system prompt is defined but not included in the agent's `_call_llm` call.

## Internal Dependencies

| Dependency | Source | Used By | Purpose |
|-----------|--------|---------|---------|
| `BaseAgent` | `job_hunter_agents.agents.base` | Both agents | LLM calling, cost tracking, error recording, logging |
| `CandidateProfile` | `job_hunter_core.models.candidate` | `ResumeParserAgent` | LLM response model / output type |
| `SearchPreferences` | `job_hunter_core.models.candidate` | `PrefsParserAgent` | LLM response model / output type |
| `PipelineState` | `job_hunter_core.state` | Both agents | Input/output state container |
| `PDFParser` | `job_hunter_agents.tools.pdf_parser` | `ResumeParserAgent` | PDF text extraction (pdfplumber -> pypdf fallback chain) |
| `RESUME_PARSER_USER` | `job_hunter_agents.prompts.resume_parser` | `ResumeParserAgent` | Prompt template |
| `PREFS_PARSER_USER` | `job_hunter_agents.prompts.prefs_parser` | `PrefsParserAgent` | Prompt template |
| `Settings` | `job_hunter_core.config.settings` | Both (via `BaseAgent.__init__`) | `haiku_model`, `anthropic_api_key`, cost guardrails |

## External Dependencies

| Package | Used By | Purpose |
|---------|---------|---------|
| `anthropic` | `BaseAgent` (inherited) | Async Anthropic SDK client for Claude API |
| `instructor` | `BaseAgent` (inherited) | Structured LLM output via Pydantic validation |
| `tenacity` | `BaseAgent` (inherited) | Retry with exponential backoff for LLM calls |
| `structlog` | Both agents | Structured logging |
| `pdfplumber` | `PDFParser` (indirect) | Primary PDF text extraction |
| `pypdf` | `PDFParser` (indirect) | Fallback PDF text extraction |
| `pydantic` | `CandidateProfile`, `SearchPreferences` | Model validation and serialization |

## Data Flow

### Resume Parsing

```
state.config.resume_path (Path to .pdf file)
    |
    v
PDFParser.extract_text()
    |  (tries pdfplumber -> pypdf)
    |  raises ScannedPDFError if no text layer
    |  raises EncryptedPDFError if password-protected
    |  raises InvalidFileError if not a .pdf
    v
raw_text (str)
    |
    +---> hashlib.sha256() ---> content_hash (str, 64-char hex)
    |
    v
RESUME_PARSER_USER.format(resume_text=raw_text)
    |
    v
BaseAgent._call_llm(model=haiku, response_model=CandidateProfile)
    |  (instructor enforces Pydantic schema)
    |  (tenacity retries up to 3 times with exponential backoff)
    |  (cost tracked on state: total_tokens, total_cost_usd)
    v
CandidateProfile (from LLM)
    |
    +---> profile.raw_text = raw_text
    +---> profile.content_hash = content_hash
    |
    v
state.profile = profile
```

### Preferences Parsing

```
state.config.preferences_text (str, freeform user input)
    |
    v
PREFS_PARSER_USER.format(preferences_text=state.config.preferences_text)
    |
    v
BaseAgent._call_llm(model=haiku, response_model=SearchPreferences)
    |  (instructor enforces Pydantic schema)
    |  (tenacity retries up to 3 times with exponential backoff)
    |  (cost tracked on state)
    v
SearchPreferences (from LLM)
    |
    +---> prefs.raw_text = state.config.preferences_text
    |
    v
state.preferences = prefs
```

### Pipeline Position

```
Pipeline step order:
  1. ResumeParserAgent.run()   <-- writes state.profile
  2. PrefsParserAgent.run()    <-- writes state.preferences
  3. CompanyFinderAgent.run()   (reads state.profile + state.preferences)
  4. JobsScraperAgent.run()
  5. ...
```

Both parsing agents can run independently of each other (neither reads the other's output), but both must complete before `CompanyFinderAgent` executes.

## Configuration

| Setting | Default | Used By | Purpose |
|---------|---------|---------|---------|
| `haiku_model` | `"claude-haiku-4-5-20251001"` | Both agents | LLM model for parsing (fast, cheap) |
| `anthropic_api_key` | required (`SecretStr`) | Both agents (via `BaseAgent`) | Authentication for Anthropic API |
| `max_cost_per_run_usd` | `5.0` | Both agents (via `_track_cost`) | Hard stop if cumulative cost exceeds this |
| `warn_cost_threshold_usd` | `2.0` | Both agents (via `_track_cost`) | Logs a warning at this threshold |

Parsing uses the Haiku model (not Sonnet) because the task is straightforward extraction with well-defined output schemas. This keeps cost and latency low.

## Error Handling

### ResumeParserAgent

| Error | Source | Behavior |
|-------|--------|----------|
| `InvalidFileError` | `PDFParser._validate_file()` | File not found or not `.pdf`. Propagates up -- fatal, pipeline stops. |
| `EncryptedPDFError` | `PDFParser._try_pdfplumber()` or `_try_pypdf()` | Password-protected PDF. Propagates up -- fatal. |
| `ScannedPDFError` | `PDFParser.extract_text()` | No text layer after both extraction attempts. Propagates up -- fatal. |
| `anthropic.APIError` | `_call_llm` via `instructor` | Retried up to 3 times with exponential backoff (1s min, 10s max). If all retries fail, propagates up. |
| `pydantic.ValidationError` | `instructor` response validation | LLM output did not match `CandidateProfile` schema. Retried by instructor (up to `max_retries`). |
| `CostLimitExceededError` | `BaseAgent._track_cost()` | Cumulative run cost exceeded `max_cost_per_run_usd`. Propagates up -- fatal. |

### PrefsParserAgent

| Error | Source | Behavior |
|-------|--------|----------|
| `anthropic.APIError` | `_call_llm` via `instructor` | Retried up to 3 times with exponential backoff. |
| `pydantic.ValidationError` | `instructor` response validation | LLM output did not match `SearchPreferences` schema. Retried by instructor. |
| `CostLimitExceededError` | `BaseAgent._track_cost()` | Propagates up -- fatal. |

Both agents have no internal error recovery beyond the retry mechanism in `_call_llm`. All exceptions propagate to the Pipeline orchestrator, which records them as `AgentError` and determines whether to continue or abort.

## Testing

### Existing Tests

**`tests/unit/agents/test_resume_parser.py`** -- `TestResumeParserAgent` (2 tests):

| Test | What It Verifies |
|------|-----------------|
| `test_run_parses_resume` | PDFParser is called, `_call_llm` returns a profile, `state.profile` is set with correct name. Mocks: `PDFParser` (returns "Resume text here"), `_call_llm` (returns pre-built `CandidateProfile`), `AsyncAnthropic`, `instructor`. |
| `test_run_sets_content_hash` | `content_hash` on the profile is a 64-character hex string (SHA-256). Mocks: same as above but PDFParser returns "text". |

**`tests/unit/agents/test_prefs_parser.py`** -- `TestPrefsParserAgent` (2 tests):

| Test | What It Verifies |
|------|-----------------|
| `test_run_parses_preferences` | `_call_llm` returns preferences, `state.preferences` is set with correct `target_titles`. Verifies `raw_text` is set to the original input. Mocks: `_call_llm` (returns pre-built `SearchPreferences`), `AsyncAnthropic`, `instructor`. |
| `test_run_preserves_raw_text` | `raw_text` on preferences equals `state.config.preferences_text`, even when the LLM returns an empty `raw_text`. |

### Test Patterns

Both test files follow the same pattern:
- `_make_settings()` creates a mock `Settings` object with `anthropic_api_key`, `haiku_model`, and cost guardrail values.
- `_call_llm` is patched at the class level (`patch.object`) to return a pre-constructed Pydantic model.
- `AsyncAnthropic` and `instructor` are patched in `job_hunter_agents.agents.base` to prevent real client instantiation during `__init__`.
- For `ResumeParserAgent`, `PDFParser` is additionally patched with an `AsyncMock` for `extract_text`.

### Gaps / Potential Additions

- No test for LLM retry behavior (e.g., first call fails, second succeeds).
- No test for `CostLimitExceededError` triggered during parsing.
- No test for `PDFParser` failures (`ScannedPDFError`, `EncryptedPDFError`, `InvalidFileError`).
- No test verifying that `RESUME_PARSER_USER` template is correctly formatted with the extracted text.
- No integration test with a real PDF fixture.

## Common Modification Patterns

### Update a parsing prompt

1. Edit the template in `src/job_hunter_agents/prompts/resume_parser.py` or `prefs_parser.py`.
2. If adding new placeholder variables, update the `.format()` call in the corresponding agent's `run()` method.
3. Bump the prompt version constant in `src/job_hunter_core/constants.py` (`RESUME_PARSER_PROMPT_VERSION` or `PREFS_PARSER_PROMPT_VERSION`) to invalidate any cached results.
4. Run `make lint && make test` to verify nothing broke.

If you want to start using the system prompt (currently defined but unused):
1. Add a `{"role": "system", "content": RESUME_PARSER_SYSTEM}` entry before the user message in the agent's `messages` list. Note: the Anthropic API uses `system` as a top-level parameter, not a message role. You may need to pass it via the `system` kwarg to `_instructor.messages.create()` instead.
2. Import the system prompt constant in the agent module.

### Add a new field to the parser output

**For CandidateProfile (resume parsing):**

1. Add the field to `CandidateProfile` in `src/job_hunter_core/models/candidate.py` with a `Field(description=...)` for instructor to use as LLM guidance.
2. If the field should not be LLM-extracted (like `content_hash`), give it a default value and set it programmatically in `ResumeParserAgent.run()` after the LLM call.
3. Update the prompt template if the LLM needs explicit instructions about the new field.
4. Update `PipelineState.to_checkpoint()` and `from_checkpoint()` if the field affects serialization (typically automatic since the whole profile is serialized).
5. Update the `_make_profile()` factory in `tests/unit/agents/test_resume_parser.py`.
6. Update `make_candidate_profile()` in `tests/mocks/mock_factories.py`.
7. If the field is used downstream, update consumers (e.g., `CompanyFinderAgent`, `JobsScorerAgent`).

**For SearchPreferences (preferences parsing):**

1. Add the field to `SearchPreferences` in `src/job_hunter_core/models/candidate.py`.
2. If the field has complex parsing rules, add guidance to `PREFS_PARSER_SYSTEM` or `PREFS_PARSER_USER`.
3. If the field has validation constraints, add a `@model_validator`.
4. Update the `SearchPreferences(raw_text="")` instances in `tests/unit/agents/test_prefs_parser.py`.
5. Update `make_search_preferences()` in `tests/mocks/mock_factories.py`.
6. If the field is used by `CompanyFinderAgent`, update the prompt template in `prompts/company_finder.py` and the `.format()` call in `_generate_candidates()`.

## Cross-References

- **SPEC_01** -- `CandidateProfile`, `SearchPreferences`, `PipelineState`, `RunConfig`, and exceptions are all defined in the core models spec.
- **SPEC_04** -- `BaseAgent` provides `_call_llm()`, `_track_cost()`, `_record_error()`, `_log_start()`, `_log_end()`. The `Pipeline` orchestrator calls these agents in sequence.
- **SPEC_06** -- `CompanyFinderAgent` is the immediate downstream consumer: it reads `state.profile` and `state.preferences` to generate target companies.
- **SPEC_07** -- `PDFParser` tool is used by `ResumeParserAgent` for text extraction. See SPEC_07 for the pdfplumber/pypdf fallback chain details.
- **SPEC_10** -- Cost tracking: both agents' `_call_llm` calls accumulate `total_tokens` and `total_cost_usd` on state via `BaseAgent._track_cost()`.
- **SPEC_11** -- Test factories `make_candidate_profile()` and `make_search_preferences()` in `tests/mocks/mock_factories.py`.
