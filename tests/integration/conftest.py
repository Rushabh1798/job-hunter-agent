"""Integration test fixtures — real DB + cache, mocked externals."""

from __future__ import annotations

import functools
import logging
import socket
import time
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from _pytest.fixtures import FixtureRequest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from job_hunter_core.config.settings import Settings
from job_hunter_infra.db.models import Base

# ---------------------------------------------------------------------------
# Service health checks (with retry for CI container start-up)
# ---------------------------------------------------------------------------


def _tcp_reachable(
    host: str,
    port: int,
    timeout: float = 1.0,
    retries: int = 15,
    delay: float = 2.0,
) -> bool:
    """Check if a TCP service is reachable, retrying on failure."""
    for attempt in range(retries):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            if attempt < retries - 1:
                time.sleep(delay)
    return False


_pg_up = _tcp_reachable("localhost", 5432, retries=15)
_redis_up = _tcp_reachable("localhost", 6379, retries=10)


@functools.cache
def _is_temporal_up() -> bool:
    """Check Temporal availability lazily (cached after first call).

    Uses only 3 retries with 1s delay (max 3s) to avoid penalizing
    test runs when Temporal is not running.
    """
    return _tcp_reachable("localhost", 7233, retries=3, delay=1.0)


# Hard-fail markers — integration tests MUST have containers running
require_postgres = pytest.mark.skipif(
    not _pg_up,
    reason="PostgreSQL not reachable on localhost:5432 — run `make dev` first",
)
require_redis = pytest.mark.skipif(
    not _redis_up,
    reason="Redis not reachable on localhost:6379 — run `make dev` first",
)

# Keep old names for backwards compat with existing test files
skip_no_postgres = require_postgres
skip_no_redis = require_redis


def skip_no_temporal[F: Callable[..., Any]](func: F) -> F:
    """Skip decorator for tests requiring Temporal (lazy check)."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        if not _is_temporal_up():
            pytest.skip("Temporal not reachable on localhost:7233 — run `make dev-temporal` first")
        return func(*args, **kwargs)

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        if not _is_temporal_up():
            pytest.skip("Temporal not reachable on localhost:7233 — run `make dev-temporal` first")
        return await func(*args, **kwargs)

    import asyncio

    if asyncio.iscoroutinefunction(func):
        return async_wrapper  # type: ignore[return-value]
    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

TEST_DB_URL = "postgresql+asyncpg://postgres:dev@localhost:5432/jobhunter_test"

_logger = logging.getLogger(__name__)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create test database and tables, drop on teardown."""
    if not _pg_up:
        pytest.skip("PostgreSQL not available")

    # Create the test database if it doesn't exist
    admin_engine = create_async_engine(
        "postgresql+asyncpg://postgres:dev@localhost:5432/postgres",
        isolation_level="AUTOCOMMIT",
    )
    async with admin_engine.connect() as conn:
        result = await conn.execute(
            __import__("sqlalchemy").text(
                "SELECT 1 FROM pg_database WHERE datname='jobhunter_test'"
            )
        )
        if not result.fetchone():
            await conn.execute(__import__("sqlalchemy").text("CREATE DATABASE jobhunter_test"))
    await admin_engine.dispose()

    # Create tables
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Teardown: drop all tables (best-effort — CI containers are ephemeral)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    except Exception:
        _logger.debug("db_engine teardown: table drop failed (expected in CI)")
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped session with savepoint rollback."""
    async_session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_factory() as session:
        async with session.begin():
            # Create savepoint
            nested = await session.begin_nested()
            yield session
            # Rollback to savepoint
            if nested.is_active:
                await nested.rollback()
            await session.rollback()


# ---------------------------------------------------------------------------
# Redis fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[object, None]:
    """Function-scoped Redis client on test DB 1, flushed before each test."""
    if not _redis_up:
        pytest.skip("Redis not available")

    from redis.asyncio import Redis

    client = Redis.from_url("redis://localhost:6379/1", decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Logging cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_logging() -> Generator[None, None, None]:
    """Save and restore root logger handlers to prevent I/O-on-closed-file errors.

    CLI tests call configure_logging() which replaces root logger handlers.
    Without cleanup, stale StreamHandlers write to pytest-captured streams
    that are already closed during teardown.
    """
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    yield
    root.handlers = original_handlers
    root.level = original_level


# ---------------------------------------------------------------------------
# Dry-run patches fixture (full mocking for pipeline logic tests)
# ---------------------------------------------------------------------------


@pytest.fixture
def dry_run_patches() -> Generator[ExitStack, None, None]:
    """Activate dry-run patches for integration tests."""
    from job_hunter_agents.dryrun import activate_dry_run_patches

    stack = activate_dry_run_patches()
    yield stack
    stack.close()


# ---------------------------------------------------------------------------
# Integration patches fixture (LLM + email + PDF only)
# ---------------------------------------------------------------------------


@pytest.fixture
def integration_patches() -> Generator[ExitStack, None, None]:
    """Activate integration patches — only LLM, email, and PDF are mocked.

    Search (DuckDuckGo), scraping (crawl4ai), and ATS clients (public APIs)
    are left real.
    """
    from job_hunter_agents.dryrun import activate_integration_patches

    stack = activate_integration_patches()
    yield stack
    stack.close()


# ---------------------------------------------------------------------------
# Real settings fixture for integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def real_settings(tmp_path: Path) -> Settings:
    """Real Settings pointing at test Postgres + Redis containers."""
    from tests.mocks.mock_settings import make_real_settings

    return make_real_settings(tmp_path)


# ---------------------------------------------------------------------------
# Pipeline tracing fixture — enables OTEL + prints run report
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline_tracing(request: FixtureRequest) -> Generator[object, None, None]:
    """Enable OTEL tracing with InMemorySpanExporter and print run report.

    Automatically detects mock mode from co-active patch fixtures:
    - integration_patches -> 'integration'
    - dry_run_patches -> 'dry_run'
    - neither -> 'live'

    After the test, collects all spans and prints a formatted run report
    to stdout (visible with ``pytest -s``).
    """
    otel = pytest.importorskip("opentelemetry")  # noqa: F841
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from job_hunter_agents.observability.run_report import (
        format_run_report,
        generate_run_report,
    )
    from job_hunter_agents.observability.tracing import (
        configure_tracing_with_exporter,
        disable_tracing,
    )

    exporter = InMemorySpanExporter()
    configure_tracing_with_exporter("job-hunter-test", exporter)

    yield exporter

    # Determine mock mode from active fixtures
    active_fixtures = request.fixturenames
    if "integration_patches" in active_fixtures:
        mock_mode = "integration"
    elif "dry_run_patches" in active_fixtures:
        mock_mode = "dry_run"
    else:
        mock_mode = "live"

    # Generate and print run report
    spans = exporter.get_finished_spans()
    report = generate_run_report(spans, mock_mode=mock_mode)
    print(format_run_report(report))

    disable_tracing()
