"""
Database-backed fixtures.

These used to need `make infra` up, a Postgres container, and a `<database>_test`
database created by hand — which is why they were never part of a quick loop and why
CI had to provision services before it could run them.

They run against a temporary SQLite file now, like everything else. Nothing to start,
nothing to create, and the suite is the same suite.

A file rather than `:memory:`: the application opens its own connections through
`AsyncSessionLocal`, and an in-memory database is private to the connection that
created it, so the app would see an empty schema.
"""

import os
import tempfile
import uuid
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from codelith.db.base import Base
from codelith.dependencies import get_db
from codelith.main import app


def _test_database_url() -> str:
    """A fresh file per run, in the system temp directory. Override with
    `TEST_DATABASE_URL`."""
    if override := os.getenv("TEST_DATABASE_URL"):
        return override
    path = Path(tempfile.gettempdir()) / f"codelith-test-{uuid.uuid4().hex}.db"
    return f"sqlite+aiosqlite:///{path.as_posix()}"


TEST_DATABASE_URL = _test_database_url()

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    # The app writes from a background thread while a test reads on another.
    connect_args={"check_same_thread": False},
)
# The same pragmas the application sets. Foreign keys are off by default in SQLite,
# so without this every `ondelete="CASCADE"` the models declare would do nothing — and
# the cascade tests would be asserting against a database that does not enforce them.
if TEST_DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event

    from codelith.db.session import tune_sqlite

    event.listen(test_engine.sync_engine, "connect", tune_sqlite)

TestSessionLocal = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await test_engine.dispose()
    # Best effort. On Windows a connection the application opened may still hold the
    # file, and a failure to tidy up a temp file must not fail the suite that passed.
    if TEST_DATABASE_URL.startswith("sqlite"):
        try:
            Path(TEST_DATABASE_URL.split("///", 1)[-1]).unlink(missing_ok=True)
        except OSError:
            pass


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
