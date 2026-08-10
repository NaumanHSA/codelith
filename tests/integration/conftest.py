"""
Database-backed fixtures.

Scoped to `tests/integration` so unit tests never require Postgres. Needs the infra
stack up (`make infra`) and a `<database>_test` database to exist.
"""

import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from codelith.config import get_settings
from codelith.db.base import Base
from codelith.dependencies import get_db
from codelith.main import app


def _test_database_url() -> str:
    """
    Derive the test DB URL from the configured one so it follows host/port changes
    instead of hardcoding them. Override with TEST_DATABASE_URL.
    """
    if override := os.getenv("TEST_DATABASE_URL"):
        return override
    prefix, _, name = get_settings().DATABASE_URL.rpartition("/")
    return f"{prefix}/{name}_test"


TEST_DATABASE_URL = _test_database_url()

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        # pgvector must exist before CodeChunk.embedding can be created.
        from sqlalchemy import text

        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


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
