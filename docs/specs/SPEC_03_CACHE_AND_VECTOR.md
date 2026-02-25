# SPEC_03: Cache and Vector

## Purpose

Provides swappable caching backends (Redis for production, database-backed for `--lite` mode) and brute-force vector similarity search for SQLite mode. All caching flows through the `CacheClient` protocol defined in SPEC_01, enabling domain-specific cache wrappers (company URLs, scraped pages) to remain backend-agnostic.

## Key Files

| File | Primary Exports | Lines |
|------|----------------|-------|
| `src/job_hunter_infra/cache/redis_cache.py` | `RedisCacheClient` | 35 |
| `src/job_hunter_infra/cache/db_cache.py` | `CacheEntry` (ORM), `DBCacheClient` | 81 |
| `src/job_hunter_infra/cache/company_cache.py` | `CompanyURLCache` | 25 |
| `src/job_hunter_infra/cache/page_cache.py` | `PageCache` | 27 |
| `src/job_hunter_infra/vector/similarity.py` | `cosine_similarity`, `find_top_k_similar` | 53 |
| `src/job_hunter_core/interfaces/cache.py` | `CacheClient` (Protocol) | 27 |

## Public API

### CacheClient Protocol (`job_hunter_core.interfaces.cache`)

```python
@runtime_checkable
class CacheClient(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_seconds: int = 86400) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
```

All values are strings. Higher-level consumers are responsible for serialization (e.g., `json.dumps`/`json.loads` for embeddings). Default TTL across the protocol is **86400 seconds (24 hours)**.

---

### RedisCacheClient (`job_hunter_infra.cache.redis_cache`)

```python
class RedisCacheClient:
    def __init__(self, redis: Redis) -> None
```

**Constructor:**
- `redis` -- an instance of `redis.asyncio.Redis`. The caller is responsible for creating and managing the connection lifecycle (including `aclose()`).

**Methods:**

| Method | Behavior |
|--------|----------|
| `get(key: str) -> str \| None` | Calls `redis.get(key)`. Returns `None` on miss. Decodes `bytes` to `str` via UTF-8. If value is already a `str` (e.g., `decode_responses=True`), coerces via `str()`. |
| `set(key: str, value: str, ttl_seconds: int = 86400) -> None` | Calls `redis.set(name=key, value=value, ex=ttl_seconds)`. TTL is always set -- there is no "no expiry" mode. |
| `delete(key: str) -> None` | Calls `redis.delete(key)`. No-op if key does not exist. |
| `exists(key: str) -> bool` | Calls `redis.exists(key)` and converts the integer count to `bool`. |

**Edge cases:**
- Redis returns `bytes` by default unless `decode_responses=True` is set on the client. `RedisCacheClient.get()` handles both cases.
- TTL expiry is handled entirely by Redis (server-side). No application-side expiry logic.
- No connection pooling or retry logic in this class; those concerns belong to the `Redis` client configuration at the composition root.

---

### DBCacheClient (`job_hunter_infra.cache.db_cache`)

```python
class DBCacheClient:
    def __init__(self, session: AsyncSession) -> None
```

**Constructor:**
- `session` -- an `sqlalchemy.ext.asyncio.AsyncSession`. The caller manages the session lifecycle. Each operation commits immediately.

**Methods:**

| Method | Behavior |
|--------|----------|
| `get(key: str) -> str \| None` | Fetches `CacheEntry` by primary key. If found but expired, **deletes the entry and commits**, then returns `None`. If not expired, returns `entry.value`. |
| `set(key: str, value: str, ttl_seconds: int = 86400) -> None` | Computes `expires_at = now(UTC) + timedelta(seconds=ttl_seconds)`. If key exists, updates `value` and `expires_at`. If key does not exist, inserts a new `CacheEntry`. **Commits immediately.** |
| `delete(key: str) -> None` | Fetches entry by primary key. If found, deletes and commits. If not found, silently returns (no error). |
| `exists(key: str) -> bool` | Runs a `SELECT` query for the key. If found but expired, **deletes the entry and commits**, returns `False`. Otherwise returns `True`. |

**Edge cases:**
- **Lazy expiry cleanup**: Expired entries are only removed when accessed via `get()` or `exists()`. There is no background sweep/purge process.
- **Timezone handling**: The private helper `_is_expired(expires_at)` handles both naive and timezone-aware datetimes. Naive datetimes are assumed UTC by calling `replace(tzinfo=UTC)` before comparison. This accommodates SQLite's lack of timezone-aware datetime storage.
- **Upsert on set**: The `set()` method performs a read-then-write upsert pattern (not a SQL `ON CONFLICT`), which is safe within a single session but not concurrency-safe across multiple DB sessions writing the same key.

---

### CacheEntry ORM Model (`job_hunter_infra.cache.db_cache`)

```python
class CacheEntry(Base):
    __tablename__ = "cache_entries"

    key: Mapped[str]       # String(512), primary_key=True
    value: Mapped[str]     # String (unbounded), NOT NULL
    expires_at: Mapped[datetime | None]  # nullable=True
```

- **Table**: `cache_entries`
- **Primary key**: `key` (max 512 characters)
- **No `created_at`/`updated_at`** -- unlike other ORM models in the project, this table is deliberately minimal since cached values are ephemeral.
- **Inherits from** `job_hunter_infra.db.models.Base`, so it is included in `Base.metadata.create_all()` migrations.
- The `value` column has no length limit (`String` without argument), allowing arbitrarily large cached values (e.g., full scraped page HTML or serialized embedding vectors).

---

### CompanyURLCache (`job_hunter_infra.cache.company_cache`)

```python
class CompanyURLCache:
    def __init__(self, cache: CacheClient) -> None
```

**Constructor:**
- `cache` -- any `CacheClient` implementation (Redis or DB).

**Key pattern**: `company_url:{normalized_name}`
- Normalization: `company_name.lower().strip()`
- Example: `"  Stripe  "` produces key `company_url:stripe`
- Example: `"Google"` produces key `company_url:google`

**Methods:**

| Method | Signature | Default TTL | Behavior |
|--------|-----------|-------------|----------|
| `get_career_url` | `(company_name: str) -> str \| None` | N/A (read) | Normalizes name, calls `cache.get()`. Returns the cached career URL or `None`. |
| `set_career_url` | `(company_name: str, url: str, ttl_days: int = 7) -> None` | 7 days (604,800 seconds) | Normalizes name, calls `cache.set()` with `ttl_seconds=ttl_days * 86400`. |

**Edge cases:**
- Key normalization is case-insensitive and strips whitespace, so `"Stripe"`, `"stripe"`, and `"  STRIPE  "` all resolve to the same cache key.
- The TTL is expressed in days (not hours or seconds) since career URLs change infrequently.
- There is no `delete_career_url` method. Entries expire naturally via TTL.

---

### PageCache (`job_hunter_infra.cache.page_cache`)

```python
class PageCache:
    def __init__(self, cache: CacheClient) -> None
```

**Constructor:**
- `cache` -- any `CacheClient` implementation (Redis or DB).

**Key pattern**: `page:{sha256_hex}`
- Hash input: `url.encode()` (raw URL bytes, no normalization)
- Example: `"https://stripe.com/jobs"` produces key `page:` followed by the full 64-character SHA-256 hex digest of that URL string.
- The SHA-256 hash ensures fixed-length keys regardless of URL length, and avoids issues with special characters in URLs.

**Methods:**

| Method | Signature | Default TTL | Behavior |
|--------|-----------|-------------|----------|
| `get_page` | `(url: str) -> str \| None` | N/A (read) | Hashes URL, calls `cache.get()`. Returns cached page HTML/content or `None`. |
| `set_page` | `(url: str, content: str, ttl_hours: int = 24) -> None` | 24 hours (86,400 seconds) | Hashes URL, calls `cache.set()` with `ttl_seconds=ttl_hours * 3600`. |

**Edge cases:**
- URLs are **not** normalized before hashing. `"https://example.com"` and `"https://example.com/"` produce different cache keys. This is intentional: URL normalization is the caller's responsibility.
- The cached value is the full page content (HTML string). For large pages this may be several hundred KB. No compression is applied.
- There is no `delete_page` method. Entries expire naturally via TTL.

---

### CachedEmbedder (consumer, defined in `job_hunter_agents.tools.embedder`)

While not part of the cache infrastructure package, this class is a key consumer of `CacheClient` and demonstrates the cache key pattern for embeddings:

**Key pattern**: `emb:{sha256_hex}`
- Hash input: `text.encode()` (raw text bytes)
- Cached value: `json.dumps(embedding)` -- a JSON-serialized `list[float]`
- Default TTL: **30 days** (`86400 * 30 = 2,592,000 seconds`)
- On cache hit: returns `json.loads(cached_value)`

---

### cosine_similarity (`job_hunter_infra.vector.similarity`)

```python
def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float
```

Computes the cosine similarity between two float vectors using NumPy.

**Behavior:**
- Converts inputs to `np.float32` arrays.
- Returns `dot(a, b) / (norm(a) * norm(b))`.
- If either vector has zero norm, returns `0.0` (avoids division by zero).
- Return range: `[-1.0, 1.0]` for unit vectors. Identical vectors return `1.0`, orthogonal vectors return `0.0`, opposite vectors return `-1.0`.

**Edge cases:**
- Zero-length vectors (all zeros): returns `0.0`, not `NaN`.
- Vectors must be the same length; mismatched lengths will raise a NumPy broadcasting error (not caught).
- Uses `float32` precision, not `float64`. Sufficient for embedding comparisons but introduces minor floating-point differences vs. `float64`.

---

### find_top_k_similar (`job_hunter_infra.vector.similarity`)

```python
def find_top_k_similar(
    query: list[float],
    candidates: list[tuple[str, list[float]]],
    top_k: int = 50,
) -> list[tuple[str, float]]
```

Brute-force top-K nearest-neighbor search by cosine similarity. Used in SQLite/`--lite` mode where pgvector is not available.

**Parameters:**
- `query` -- the query embedding vector.
- `candidates` -- list of `(id, embedding)` tuples where `id` is any string identifier (typically a UUID string).
- `top_k` -- maximum number of results to return. Default: `50`.

**Return:** list of `(id, similarity_score)` tuples, sorted by score descending, truncated to `top_k`.

**Behavior:**
1. If `candidates` is empty, returns `[]`.
2. Converts `query` to `np.float32` and computes its norm. If query norm is `0.0`, returns `[]`.
3. Iterates over all candidates. For each candidate:
   - Converts embedding to `np.float32`, computes norm.
   - If candidate norm is `0.0`, **skips** (does not include in results).
   - Otherwise computes cosine similarity and appends to scores.
4. Sorts scores descending by similarity.
5. Returns the top `top_k` entries.

**Edge cases:**
- Zero query vector: returns `[]` (early return).
- Zero candidate vectors: silently skipped (not included in results).
- Fewer candidates than `top_k`: returns all non-zero candidates.
- **O(n) complexity**: iterates over every candidate. Suitable for up to a few thousand candidates. For larger datasets, pgvector with ANN indexing is preferred.
- The `top_k` default of `50` aligns with `Settings.top_k_semantic`.

## Internal Dependencies

| Dependency | Source | Used By |
|------------|--------|---------|
| `CacheClient` (Protocol) | `job_hunter_core.interfaces.cache` (SPEC_01) | `CompanyURLCache`, `PageCache` -- both accept any `CacheClient` implementation |
| `Base` (DeclarativeBase) | `job_hunter_infra.db.models` (SPEC_02) | `CacheEntry` inherits from `Base`, included in schema migrations |

**Dependency direction:**
- `job_hunter_core` defines the `CacheClient` protocol (zero deps).
- `job_hunter_infra.cache` provides implementations (`RedisCacheClient`, `DBCacheClient`) and domain wrappers (`CompanyURLCache`, `PageCache`).
- `job_hunter_agents.tools.embedder` consumes `CacheClient` for embedding caching.
- No circular dependencies: infrastructure never imports from agents.

## External Dependencies

| Package | Version Constraint | Used By | Purpose |
|---------|-------------------|---------|---------|
| `redis` | `>=5.0` | `RedisCacheClient` | Async Redis client (`redis.asyncio.Redis`) |
| `numpy` | `>=1.26` | `cosine_similarity`, `find_top_k_similar` | Vector math: `np.dot`, `np.linalg.norm`, `np.array` |
| `sqlalchemy` | `>=2.0` (implied) | `DBCacheClient`, `CacheEntry` | Async ORM for DB-backed cache |
| `aiosqlite` | (transitive) | `DBCacheClient` in `--lite` mode | SQLite async driver |
| `asyncpg` | (transitive) | `DBCacheClient` in postgres mode | PostgreSQL async driver |

## Data Flow

### Cache Read Path

```
Caller (e.g., CompanyFinderAgent)
    │
    ▼
CompanyURLCache.get_career_url("Stripe")
    │
    ├── _key("Stripe") → "company_url:stripe"
    │
    ▼
CacheClient.get("company_url:stripe")
    │
    ├── [Redis backend] → redis.get("company_url:stripe")
    │       └── Returns bytes/str or None (server-side TTL check)
    │
    └── [DB backend] → SELECT * FROM cache_entries WHERE key = "company_url:stripe"
            ├── Not found → return None
            ├── Found, expired → DELETE + COMMIT → return None
            └── Found, valid → return entry.value
```

### Cache Write Path

```
Caller (e.g., CareerPageScraperAgent)
    │
    ▼
PageCache.set_page("https://stripe.com/jobs", "<html>...", ttl_hours=24)
    │
    ├── _key("https://stripe.com/jobs") → "page:{sha256_hex}"
    │
    ▼
CacheClient.set("page:{sha256_hex}", "<html>...", ttl_seconds=86400)
    │
    ├── [Redis backend] → redis.set(name=..., value=..., ex=86400)
    │
    └── [DB backend] → GET existing entry
            ├── Exists → UPDATE value, expires_at → COMMIT
            └── Not exists → INSERT new CacheEntry → COMMIT
```

### Cache Key Patterns Summary

| Domain | Key Pattern | Example | Default TTL |
|--------|------------|---------|-------------|
| Company career URLs | `company_url:{name.lower().strip()}` | `company_url:stripe` | 7 days |
| Scraped pages | `page:{sha256(url)}` | `page:a1b2c3...` (64 hex chars) | 24 hours |
| Embeddings | `emb:{sha256(text)}` | `emb:d4e5f6...` (64 hex chars) | 30 days |
| Raw (direct use) | Caller-defined | Any string up to 512 chars (DB) | 24 hours (default) |

### Vector Similarity Flow

```
SemanticFilterAgent
    │
    ├── 1. Get query embedding from CandidateProfile
    │
    ├── 2. Collect candidate embeddings from NormalizedJob list
    │       → list[tuple[str_id, list[float]]]
    │
    ├── 3. find_top_k_similar(query, candidates, top_k=50)
    │       │
    │       ├── Convert to np.float32
    │       ├── Compute cosine similarity for each candidate
    │       ├── Sort descending
    │       └── Return top_k (id, score) pairs
    │
    └── 4. Filter NormalizedJob list to top-K matches
```

## Configuration

All cache and vector settings are in `Settings` (SPEC_01), prefixed with `JH_` for environment variables.

| Settings Field | Type | Default | Env Var | Purpose |
|---------------|------|---------|---------|---------|
| `cache_backend` | `Literal["redis", "db"]` | `"redis"` | `JH_CACHE_BACKEND` | Selects `RedisCacheClient` or `DBCacheClient` |
| `redis_url` | `str` | `"redis://localhost:6379/0"` | `JH_REDIS_URL` | Redis connection URL (only used when `cache_backend="redis"`) |
| `cache_ttl_hours` | `int` | `24` | `JH_CACHE_TTL_HOURS` | Default page cache TTL |
| `company_cache_ttl_days` | `int` | `7` | `JH_COMPANY_CACHE_TTL_DAYS` | Company URL cache TTL |
| `top_k_semantic` | `int` | `50` | `JH_TOP_K_SEMANTIC` | Default `top_k` for vector similarity search |
| `embedding_dimension` | `int` | `384` | `JH_EMBEDDING_DIMENSION` | Expected embedding vector dimension (384 for MiniLM, 1024 for Voyage) |

**Validation:**
- `validate_cache_config()` on `Settings` raises `ValueError` if `cache_backend="redis"` and `redis_url` is empty.

**Lite mode (`--lite`):**
- Sets `cache_backend="db"` and `db_backend="sqlite"`, so `DBCacheClient` is used with an in-process SQLite database. Zero external infrastructure required.

## Error Handling

### RedisCacheClient

- **Connection errors**: Not caught within the class. A `redis.ConnectionError` or `redis.TimeoutError` will propagate to the caller. The composition root should configure the `Redis` client with appropriate retry policies and timeouts.
- **Serialization errors**: Not applicable -- values are always strings.

### DBCacheClient

- **Session errors**: `SQLAlchemy` exceptions (`OperationalError`, `IntegrityError`) propagate uncaught. The caller (typically the pipeline or agent) should handle DB connectivity issues.
- **Commit failures**: Each method commits immediately. If a commit fails, the exception propagates, and the session may be in an inconsistent state. Callers should use a fresh session or rollback.
- **Expiry race condition**: Two concurrent sessions could both read the same expired entry. Both would attempt to delete it; the second delete is a no-op (entry already gone). This is benign.

### Vector Similarity

- **Mismatched dimensions**: If `query` and a candidate embedding have different lengths, `np.dot` will raise a `ValueError`. No explicit dimension validation is performed in the function.
- **NaN/Inf in vectors**: Not explicitly handled. Could produce `NaN` similarity scores. Callers should validate embeddings before passing to similarity functions.
- **Memory**: All candidates are loaded into memory. For very large candidate sets (>100K), this could cause memory pressure. The expected usage is hundreds to low thousands of candidates.

## Testing

### Unit Tests

| Test File | Test Class | What It Tests |
|-----------|-----------|---------------|
| `tests/unit/infra/test_cache_backends.py` | `TestDBCacheClient` | `set`/`get` roundtrip, missing key returns `None`, `exists`/`delete`, expired entry returns `None` and is deleted, overwrite existing key, delete nonexistent key is no-op |
| `tests/unit/infra/test_cache_backends.py` | `TestRedisCacheClient` | `get` decodes bytes to str, `get` returns `None` on miss, `set` passes name/value/ex to Redis, `delete` forwards to Redis, `exists` true/false, non-bytes value coerced to str |
| `tests/unit/infra/test_cache_backends.py` | `TestPageCache` | `set_page`/`get_page` roundtrip with TTL conversion (hours to seconds), miss returns `None`, key is deterministic and prefixed with `page:` |
| `tests/unit/infra/test_cache_backends.py` | `TestCompanyURLCache` | `set_career_url`/`get_career_url` roundtrip with TTL conversion (days to seconds), key is case-insensitive and whitespace-stripped, miss returns `None` |
| `tests/unit/infra/test_similarity.py` | `TestCosineSimilarity` | Identical vectors (1.0), orthogonal vectors (0.0), opposite vectors (-1.0), zero vector (0.0) |
| `tests/unit/infra/test_similarity.py` | `TestFindTopKSimilar` | Basic ranking correctness, `top_k` limits output size, empty candidates returns `[]`, zero query vector returns `[]` |

### Integration Tests

| Test File | Test Class | What It Tests |
|-----------|-----------|---------------|
| `tests/integration/test_cache_redis.py` | `TestRedisCacheClient` | Real Redis `set`/`get` roundtrip, missing key, TTL expiry (1s sleep), `delete`/`exists`, 10 concurrent set/get operations |

**Mocking strategy:**
- **Unit tests for `RedisCacheClient`**: Mock `redis.asyncio.Redis` using `MagicMock` with `AsyncMock` methods. Verifies that the correct Redis commands are called with correct arguments.
- **Unit tests for `DBCacheClient`**: Real in-memory SQLite via `create_async_engine("sqlite+aiosqlite:///:memory:")`. Tables created from `Base.metadata`. No mocking needed.
- **Unit tests for `CompanyURLCache` and `PageCache`**: Inner `CacheClient` is a bare `AsyncMock`. Tests verify key generation logic and TTL conversion without touching any real backend.
- **Integration tests for Redis**: Requires a real Redis instance on `localhost:6379`. Uses Redis DB 1 (not 0) to avoid conflicts with development data. Flushes DB before and after each test. Skipped automatically if Redis is not reachable (`skip_no_redis` marker).
- **Vector similarity**: Pure unit tests with no mocking needed (stateless math functions).

## Common Modification Patterns

### Add a new domain cache (like CompanyURLCache)

1. Create a new file in `src/job_hunter_infra/cache/`, e.g., `embedding_cache.py`.
2. Accept `CacheClient` in the constructor (dependency injection):
   ```python
   class EmbeddingCache:
       def __init__(self, cache: CacheClient) -> None:
           self._cache = cache

       def _key(self, text_hash: str) -> str:
           return f"emb:{text_hash}"

       async def get_embedding(self, text_hash: str) -> str | None:
           return await self._cache.get(self._key(text_hash))

       async def set_embedding(self, text_hash: str, value: str, ttl_days: int = 30) -> None:
           await self._cache.set(self._key(text_hash), value, ttl_seconds=ttl_days * 86400)
   ```
3. Choose a unique key prefix (e.g., `emb:`) to avoid collisions with existing patterns (`company_url:`, `page:`).
4. Add unit tests in `tests/unit/infra/test_cache_backends.py` following the `TestCompanyURLCache` pattern: mock the inner `CacheClient` with `AsyncMock`, verify key generation and TTL conversion.
5. Wire the new cache wrapper at the composition root, passing the same `CacheClient` instance used by other caches.

### Change cache backend

The backend is selected by `Settings.cache_backend` (`"redis"` or `"db"`). To change:

1. **At runtime**: Set `JH_CACHE_BACKEND=db` in environment or `.env`. No code changes needed.
2. **Add a new backend** (e.g., Memcached):
   - Create `src/job_hunter_infra/cache/memcached_cache.py` implementing the four methods of `CacheClient` (`get`, `set`, `delete`, `exists`).
   - Add `"memcached"` to the `Literal` type in `Settings.cache_backend`.
   - Add a validator in `Settings` to require the Memcached URL when selected.
   - Update the composition root to instantiate the new client when `cache_backend="memcached"`.
   - Add unit tests (mocked client) and integration tests (real Memcached).

### Add a new vector search method

1. Add the function to `src/job_hunter_infra/vector/similarity.py`.
2. Follow the existing pattern: accept `list[float]` inputs, use `np.float32`, handle zero-norm vectors gracefully.
3. Example -- Euclidean distance search:
   ```python
   def find_top_k_nearest(
       query: list[float],
       candidates: list[tuple[str, list[float]]],
       top_k: int = 50,
   ) -> list[tuple[str, float]]:
       # Similar structure to find_top_k_similar but using L2 distance
       # Sort ascending (smaller distance = more similar)
   ```
4. Add unit tests in `tests/unit/infra/test_similarity.py` covering: identical vectors, orthogonal vectors, zero vectors, empty candidates, `top_k` limiting.
5. If the function is meant to replace `find_top_k_similar` in certain contexts, update the consuming agent to accept a configurable similarity function.

## Cross-References

- **SPEC_01** (Core Models) -- defines `CacheClient` protocol, `Settings` with cache/vector configuration fields, `EmbedderBase` protocol
- **SPEC_02** (Database Layer) -- `CacheEntry` inherits from `Base` (same `DeclarativeBase` as all ORM models); included in `create_all()` migrations
- **SPEC_04** (Pipeline and Orchestration) -- pipeline wires `CacheClient` at startup based on `Settings.cache_backend`; passes to agents and tools
- **SPEC_05/06** (Agents) -- `CompanyFinderAgent` uses `CompanyURLCache`; `CareerPageScraperAgent` uses `PageCache`; `SemanticFilterAgent` uses `find_top_k_similar`
- **SPEC_07** (Tools: Embedder) -- `CachedEmbedder` wraps `CacheClient` with key pattern `emb:{sha256}` and 30-day TTL
- **SPEC_11** (Testing) -- mock factories and test fixtures in `tests/unit/infra/test_cache_backends.py`; integration fixtures in `tests/integration/conftest.py` (Redis DB 1, `skip_no_redis`)
