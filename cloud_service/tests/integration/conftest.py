"""
Integration-test fixtures.

Imported only when pytest collects tests under tests/integration/, so the
existing sys.modules stubs in test_cloud_invariants.py are unaffected.

Database strategy
-----------------
* DATABASE_URL defaults to sqlite+aiosqlite:///./test_nestor.db (set by the
  root conftest).  Override in .env.test to point at a real Postgres instance.
* A separate test engine is created here; the app's get_db dependency is
  overridden so every endpoint uses the test session, not the production pool.
* Tables are created once per session and dropped at teardown.
* Each test_db fixture yields a session that is rolled back after the test.
"""
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ── App imports (env vars already set by root conftest) ───────────────────────
from cloud_service.app import models  # noqa: F401 — registers ORM models with Base
from cloud_service.app.db import Base, get_db
from cloud_service.app.main import app

# ── Test engine ───────────────────────────────────────────────────────────────
_TEST_DB_URL = os.environ["DATABASE_URL"]

_engine_kwargs: dict = {}
if "sqlite" in _TEST_DB_URL:
    # aiosqlite needs check_same_thread=False for async use
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    if ":memory:" in _TEST_DB_URL:
        from sqlalchemy.pool import StaticPool
        _engine_kwargs["poolclass"] = StaticPool

_test_engine = create_async_engine(_TEST_DB_URL, **_engine_kwargs)
_TestSession = async_sessionmaker(
    _test_engine, expire_on_commit=False, class_=AsyncSession
)


# ── Session-scoped: create schema once, drop after all integration tests ──────
@pytest.fixture(scope="session", autouse=True)
async def create_tables():
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _test_engine.dispose()


# ── Per-test: isolated DB session, rolled back after each test ────────────────
@pytest.fixture
async def test_db(create_tables):
    async with _TestSession() as session:
        yield session
        await session.rollback()


# ── Per-test: HTTPX async client wired to the FastAPI app ────────────────────
@pytest.fixture
async def client(create_tables):
    """Async HTTP client; app's get_db is overridden to use the test DB."""

    async def _override_get_db():
        async with _TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)
