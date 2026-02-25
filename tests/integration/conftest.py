"""Integration test fixtures — real DB + cache, mocked externals."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncGenerator, Generator
from contextlib import ExitStack

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from job_hunter_infra.db.models import Base

# ---------------------------------------------------------------------------
# Service health checks
# ---------------------------------------------------------------------------


def _tcp_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP service is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_pg_up = _tcp_reachable("localhost", 5432)
_redis_up = _tcp_reachable("localhost", 6379)

skip_no_postgres = pytest.mark.skipif(
    not _pg_up,
    reason="PostgreSQL not reachable on localhost:5432 — run `make dev` first",
)
skip_no_redis = pytest.mark.skipif(
    not _redis_up,
    reason="Redis not reachable on localhost:6379 — run `make dev` first",
)


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

TEST_DB_URL = "postgresql+asyncpg://postgres:dev@localhost:5432/jobhunter_test"


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create a single event loop for all session-scoped fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
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
            await conn.execute(
                __import__("sqlalchemy").text("CREATE DATABASE jobhunter_test")
            )
    await admin_engine.dispose()

    # Create tables
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Teardown: drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
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
# Dry-run patches fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def dry_run_patches() -> Generator[ExitStack, None, None]:
    """Activate dry-run patches for integration tests."""
    from job_hunter_agents.dryrun import activate_dry_run_patches

    stack = activate_dry_run_patches()
    yield stack
    stack.close()
