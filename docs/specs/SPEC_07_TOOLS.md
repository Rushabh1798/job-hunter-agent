# SPEC_07: Tools

## Purpose

External I/O boundary -- thin async wrappers around third-party libraries. Tools have no knowledge of agents. They are instantiated and called by agents but never import agent code. Each tool encapsulates a single external service and exposes a minimal async API. Sync libraries are wrapped via `asyncio.to_thread()` to keep the async pipeline non-blocking.

## Key Files

| File | Primary Exports | Lines |
|------|----------------|-------|
| `src/job_hunter_agents/tools/pdf_parser.py` | `PDFParser` | 107 |
| `src/job_hunter_agents/tools/browser.py` | `WebScraper` | 61 |
| `src/job_hunter_agents/tools/web_search.py` | `SearchResult`, `WebSearchTool` | 73 |
| `src/job_hunter_agents/tools/embedder.py` | `LocalEmbedder`, `VoyageEmbedder`, `CachedEmbedder` | 113 |
| `src/job_hunter_agents/tools/email_sender.py` | `EmailSender` | 178 |
| `src/job_hunter_agents/tools/ats_clients/` | ATS client implementations (see SPEC_08) | -- |

## Public API

### PDFParser (`tools/pdf_parser.py`)

```python
MAX_PDF_SIZE_MB = 10  # module-level constant; warn (not error) if exceeded

class PDFParser:
    """Extract text from PDF files with multiple fallback strategies."""

    async def extract_text(self, path: Path) -> str
        """Extract text from a PDF file.
        Fallback chain: pdfplumber -> pypdf.
        Raises: InvalidFileError, EncryptedPDFError, ScannedPDFError.
        Minimum viable text threshold: 50 characters after strip()."""

    # Internal (private):
    def _validate_file(self, path: Path) -> None
        # Checks path.exists() and path.suffix == ".pdf"
    def _check_size(self, path: Path) -> None
        # Logs warning if file > MAX_PDF_SIZE_MB
    async def _try_pdfplumber(self, path: Path) -> str | None
        # Sync extraction via asyncio.to_thread(). Catches password errors -> EncryptedPDFError.
    async def _try_pypdf(self, path: Path) -> str | None
        # Sync extraction via asyncio.to_thread(). Checks reader.is_encrypted -> EncryptedPDFError.
```

**Constructor:** No parameters. Stateless.

**Fallback chain:** `pdfplumber` is tried first. If it fails or returns fewer than 50 characters, `pypdf` is tried. If both produce insufficient text, `ScannedPDFError` is raised. Password-protected PDFs raise `EncryptedPDFError` from either library. Non-PDF files or missing files raise `InvalidFileError` before any extraction is attempted.

---

### WebScraper (`tools/browser.py`)

```python
class WebScraper:
    """Primary: crawl4ai. Fallback: raw Playwright."""

    async def fetch_page(self, url: str) -> str
        """Fetch page content. Tries crawl4ai first, falls back to Playwright.
        Returns: markdown (crawl4ai) or raw HTML (Playwright)."""

    async def fetch_page_playwright(self, url: str) -> str
        """Raw Playwright fetch. Launches headless Chromium, waits for networkidle,
        returns page.content(). Timeout: 30s. Public because WorkdayClient uses it directly."""

    async def fetch_json_api(
        self, url: str, headers: dict[str, str] | None = None
    ) -> dict[str, Any]
        """Direct HTTP GET for ATS JSON APIs. Uses httpx.AsyncClient(timeout=30.0).
        Raises httpx.HTTPStatusError on non-2xx responses."""

    # Internal (private):
    async def _fetch_crawl4ai(self, url: str) -> str
        # AsyncWebCrawler.arun(). Returns result.markdown or result.html.
        # Raises ValueError if both are empty.
```

**Constructor:** No parameters. Stateless.

**Fallback chain:** `fetch_page()` tries `_fetch_crawl4ai()` first. On any exception, it logs a warning and delegates to `fetch_page_playwright()`. There is no further fallback if Playwright also fails.

---

### WebSearchTool (`tools/web_search.py`)

```python
@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    score: float

class WebSearchTool:
    def __init__(self, api_key: str) -> None
        """Initialize with Tavily API key. Creates TavilyClient immediately."""

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]
        """General-purpose web search. Wraps sync TavilyClient.search() via asyncio.to_thread()."""

    async def find_career_page(self, company_name: str) -> str | None
        """Search for a company's career page. Queries: "{company_name} careers jobs official site".
        Returns: first result URL containing career/jobs/hiring/work keywords, or first result URL,
        or None if no results."""

    async def search_jobs_on_site(
        self, domain: str, role_query: str, max_results: int = 10
    ) -> list[SearchResult]
        """Site-scoped search. Query: "site:{domain} {role_query} careers jobs"."""
```

**Constructor:** `api_key: str` -- Tavily API key (from `Settings.tavily_api_key`).

---

### LocalEmbedder (`tools/embedder.py`)

```python
class LocalEmbedder:
    """sentence-transformers based embedder. Free, fast, no API key."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None
        """Lazy-loaded. Model is not loaded until first embed call."""

    async def embed_text(self, text: str) -> list[float]
        """Embed a single text string. Returns list of floats (384-dim for default model)."""

    async def embed_batch(self, texts: list[str]) -> list[list[float]]
        """Embed multiple texts. Returns empty list for empty input.
        Uses model.encode() on the full batch (more efficient than single calls)."""

    # Internal (private):
    def _get_model(self) -> Any
        # Lazy-loads SentenceTransformer on first call.
```

**Constructor:** `model_name: str = "all-MiniLM-L6-v2"` -- Hugging Face model identifier.

---

### VoyageEmbedder (`tools/embedder.py`)

```python
class VoyageEmbedder:
    """Voyage AI embeddings via API."""

    def __init__(self, api_key: str, model: str = "voyage-2") -> None
        """Initialize with Voyage API key and model name."""

    async def embed_text(self, text: str) -> list[float]
        """Delegates to embed_batch([text])[0]."""

    async def embed_batch(self, texts: list[str]) -> list[list[float]]
        """POST to https://api.voyageai.com/v1/embeddings.
        Uses httpx.AsyncClient(timeout=60.0). Returns list of embedding vectors."""
```

**Constructor:** `api_key: str` (from `Settings.voyage_api_key`), `model: str = "voyage-2"`.

---

### CachedEmbedder (`tools/embedder.py`)

```python
class CachedEmbedder:
    """Wrapper that caches embeddings by text content hash."""

    def __init__(
        self,
        embedder: LocalEmbedder | VoyageEmbedder,
        cache: CacheClient,
    ) -> None
        """Wraps any embedder with a CacheClient (from SPEC_01 interfaces/cache.py)."""

    async def embed_text(self, text: str) -> list[float]
        """Cache key: "emb:{sha256(text)}". TTL: 30 days (86400 * 30 seconds).
        On cache hit: returns json.loads(cached). On miss: calls inner embedder, stores result."""

    async def embed_batch(self, texts: list[str]) -> list[list[float]]
        """Iterates through texts calling embed_text() individually (per-text caching)."""

    # Internal (private):
    def _cache_key(self, text: str) -> str
        # Returns "emb:{sha256_hex_digest}"
```

**Constructor:** `embedder: LocalEmbedder | VoyageEmbedder` -- the inner embedder, `cache: CacheClient` -- any implementation of the cache protocol.

---

### EmailSender (`tools/email_sender.py`)

```python
class EmailSender:
    """Send emails via SMTP or SendGrid."""

    def __init__(
        self,
        provider: str = "smtp",
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        sendgrid_api_key: str = "",
    ) -> None

    async def send(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        attachment_path: str | None = None,
    ) -> bool
        """Routes to _send_smtp or _send_sendgrid based on self._provider.
        Wraps unexpected exceptions in EmailDeliveryError. Returns True on success."""

    # Internal (private):
    async def _send_smtp(...) -> bool
        # Builds MIME message via _build_smtp_message (in thread), sends via aiosmtplib.send().
        # Uses start_tls=True.
    def _build_smtp_message(...) -> MIMEMultipart
        # Sync. Creates mixed/alternative MIME with text+html parts.
        # Optionally attaches a file (base64-encoded, application/octet-stream).
    async def _send_sendgrid(...) -> bool
        # Sync via asyncio.to_thread(). Uses SendGridAPIClient.
        # Attachment type hardcoded to xlsx MIME type.
        # Returns True if response.status_code in (200, 201, 202).
```

**Constructor parameters** map directly to `Settings` fields: `email_provider`, `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `sendgrid_api_key`.

## Internal Dependencies

- `job_hunter_core.exceptions` -- `InvalidFileError`, `ScannedPDFError`, `EncryptedPDFError`, `EmailDeliveryError` (see SPEC_01 exception hierarchy)
- `job_hunter_core.interfaces.cache.CacheClient` -- Protocol used by `CachedEmbedder`

Tools do NOT import from `job_hunter_agents`, `job_hunter_infra`, or `job_hunter_cli`.

## External Dependencies

| Tool | Library | Import Path | Purpose |
|------|---------|-------------|---------|
| PDFParser | pdfplumber | `pdfplumber` | Primary PDF text extraction |
| PDFParser | pypdf | `pypdf.PdfReader` | Fallback PDF text extraction |
| WebScraper | crawl4ai | `crawl4ai.AsyncWebCrawler` | JS-capable page fetching (markdown output) |
| WebScraper | playwright | `playwright.async_api.async_playwright` | Fallback browser-based fetching |
| WebScraper | httpx | `httpx.AsyncClient` | Direct HTTP for JSON API calls |
| WebSearchTool | tavily-python | `tavily.TavilyClient` | Web search API |
| LocalEmbedder | sentence-transformers | `sentence_transformers.SentenceTransformer` | Local embedding model |
| VoyageEmbedder | httpx | `httpx.AsyncClient` | Voyage API HTTP calls |
| EmailSender | aiosmtplib | `aiosmtplib` | Async SMTP delivery |
| EmailSender | sendgrid | `sendgrid.SendGridAPIClient`, `sendgrid.helpers.mail.*` | SendGrid API delivery |

All external libraries are lazy-imported inside methods (not at module top level) to avoid import-time failures when optional dependencies are not installed.

## Data Flow

### PDFParser
```
Path (resume.pdf)
  -> _validate_file() [checks .pdf extension, existence]
  -> _check_size()    [warns if > 10MB]
  -> _try_pdfplumber() -> str | None  [>50 chars? return]
  -> _try_pypdf()      -> str | None  [>50 chars? return]
  -> ScannedPDFError if both fail
```

### WebScraper
```
# fetch_page:
URL -> _fetch_crawl4ai() -> markdown string
       [on failure] -> fetch_page_playwright() -> raw HTML string

# fetch_json_api:
URL + optional headers -> httpx.AsyncClient.get() -> response.json() -> dict
```

### WebSearchTool
```
# search:
query string -> TavilyClient.search() -> list[SearchResult]

# find_career_page:
company_name -> search("{name} careers jobs official site")
             -> filter results for career/jobs/hiring/work keywords in URL
             -> return first match URL, or first result URL, or None

# search_jobs_on_site:
domain + role_query -> search("site:{domain} {role_query} careers jobs") -> list[SearchResult]
```

### LocalEmbedder / VoyageEmbedder
```
# LocalEmbedder:
text -> SentenceTransformer.encode() [via asyncio.to_thread] -> list[float]

# VoyageEmbedder:
text -> POST https://api.voyageai.com/v1/embeddings -> response["data"][*]["embedding"] -> list[float]
```

### CachedEmbedder
```
text -> sha256 hash -> cache.get("emb:{hash}")
  [hit]  -> json.loads(cached) -> list[float]
  [miss] -> inner_embedder.embed_text() -> cache.set("emb:{hash}", json.dumps(embedding), ttl=30d) -> list[float]
```

### EmailSender
```
to_email + subject + html_body + text_body + optional attachment_path
  -> [smtp]     -> _build_smtp_message() -> aiosmtplib.send() -> True
  -> [sendgrid] -> SendGridAPIClient.send() [via to_thread] -> True if 2xx
  -> [on error] -> EmailDeliveryError
```

## Configuration

### Settings fields used per tool

| Tool | Settings Fields |
|------|----------------|
| PDFParser | None (stateless, no config) |
| WebScraper | `scrape_timeout_seconds` (used by calling agents, not internally -- internal timeout hardcoded at 30s) |
| WebSearchTool | `tavily_api_key` (passed to constructor) |
| LocalEmbedder | `embedding_model` (passed to constructor as `model_name`) |
| VoyageEmbedder | `voyage_api_key` (passed to constructor), `embedding_model` not used (defaults to `"voyage-2"`) |
| CachedEmbedder | `cache_backend` / `redis_url` (indirectly, via the CacheClient instance passed in) |
| EmailSender | `email_provider`, `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `sendgrid_api_key` |

## Error Handling

| Exception | Raised By | When |
|-----------|-----------|------|
| `InvalidFileError` | `PDFParser._validate_file()` | File does not exist or has non-`.pdf` extension |
| `EncryptedPDFError` | `PDFParser._try_pdfplumber()`, `PDFParser._try_pypdf()` | PDF is password-protected (detected by library error message or `reader.is_encrypted`) |
| `ScannedPDFError` | `PDFParser.extract_text()` | Both pdfplumber and pypdf return fewer than 50 characters of text |
| `EmailDeliveryError` | `EmailSender.send()` | Any exception during SMTP or SendGrid delivery is caught and re-raised as `EmailDeliveryError` |
| `httpx.HTTPStatusError` | `WebScraper.fetch_json_api()`, `VoyageEmbedder.embed_batch()` | Non-2xx HTTP response from ATS API or Voyage API |
| `ValueError` | `WebScraper._fetch_crawl4ai()` | crawl4ai returns empty content (no markdown and no html) |

**Error propagation pattern:** Tools raise typed exceptions from SPEC_01. Agents catch these and either retry (via tenacity) or record them as `AgentError` in `PipelineState`. Tools never catch and swallow errors silently -- they either return a fallback value or raise.

## Testing

| Test File | Tool Under Test | Key Assertions |
|-----------|----------------|----------------|
| `tests/unit/tools/test_pdf_parser.py` | `PDFParser` | `InvalidFileError` for missing/non-PDF files, validation of existing PDF |
| `tests/unit/tools/test_browser.py` | `WebScraper` | crawl4ai success path, Playwright fallback on crawl4ai failure, `fetch_json_api` with/without headers |
| `tests/unit/tools/test_web_search.py` | `WebSearchTool` | Search result parsing, career page keyword preference, fallback to first result, None on empty results, `SearchResult` dataclass |
| `tests/unit/tools/test_embedder.py` | `LocalEmbedder`, `VoyageEmbedder`, `CachedEmbedder` | Lazy model loading, float list return, empty batch, Voyage API call, cache hit skips embedder, cache miss stores result |
| `tests/unit/tools/test_email_sender.py` | `EmailSender` | Default provider is smtp, routing to smtp/sendgrid, error wrapping to `EmailDeliveryError`, MIME message construction |

**Mock tools** in `tests/mocks/mock_tools.py`: `FakePDFParser`, `FakeWebSearchTool`, `FakeWebScraper`, `FakeEmailSender`, `FakeEmbedder`. These return fixture data from `tests/fixtures/` and match the real tool constructor signatures so they can be swapped via `dryrun.py` patches.

## Common Modification Patterns

### Add a new tool

1. Create `src/job_hunter_agents/tools/<tool_name>.py`
2. Implement as a stateless class with async methods. Lazy-import external libraries inside methods.
3. Wrap sync libraries with `asyncio.to_thread()`.
4. Raise typed exceptions from `job_hunter_core.exceptions` (add new exception types if needed per SPEC_01).
5. If the tool needs configuration, accept values as constructor parameters (do not import Settings directly).
6. Create `tests/unit/tools/test_<tool_name>.py` -- mock all external I/O.
7. Create `Fake<ToolName>` in `tests/mocks/mock_tools.py` with matching constructor signature.
8. Add patches in `src/job_hunter_agents/dryrun.py` for every agent module that imports the tool.
9. Wire the tool in the agent that uses it (see SPEC_04 for agent base patterns).

### Add a fallback strategy to an existing tool

1. Implement the new fallback as a private `async def _try_<library>(...)` method.
2. Insert it into the existing fallback chain (order by preference: most accurate first, most reliable last).
3. Return `None` or empty string from the new method on failure (do not raise).
4. The caller method (`extract_text`, `fetch_page`, etc.) checks the return value threshold before trying the next fallback.
5. Log each fallback attempt at `DEBUG` level with the library name and error.
6. Add the new library to `pyproject.toml` dependencies.
7. Update `FakeToolName` in `tests/mocks/mock_tools.py` if the public API changes.
8. Add test cases for the new fallback path in the unit test file.

## Cross-References

- **SPEC_01** -- Exception types (`InvalidFileError`, `ScannedPDFError`, `EncryptedPDFError`, `EmailDeliveryError`), `CacheClient` Protocol, `Settings` configuration
- **SPEC_04** -- `dryrun.py` patches all tools for `--dry-run` mode; Pipeline injects Settings into agent constructors
- **SPEC_06** -- `ResumeParserAgent` uses `PDFParser`; `CompanyFinderAgent` uses `WebSearchTool`; `JobsScraperAgent` uses ATS clients + `WebScraper`; `JobsScorerAgent` uses embedders; `NotifierAgent` uses `EmailSender`
- **SPEC_08** -- ATS clients are a specialized subset of tools with their own spec
- **SPEC_11** -- Fake tool implementations in `tests/mocks/mock_tools.py`
