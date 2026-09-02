"""
Getting a new database to head without running a migration.

The database is a file this process owns. On a machine that has never run Codelith it
does not exist, and an empty one is indistinguishable from a first launch — so the
schema is built from the models and the chain stamped as applied. There is no separate
migrate step to forget.

Existing databases are left alone: `alembic upgrade head` is still how a schema moves
forward once there is data in it, and the *next* migration applies normally because
the version table says where this started.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)


def _alembic_config(url: str):
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    # `alembic/env.py` overrides the URL from settings unless told not to. Without
    # this flag a stamp aimed at a solo database lands on the configured Postgres.
    cfg.attributes["url_set_by_caller"] = True
    return cfg


async def ensure_schema(engine: AsyncEngine) -> bool:
    """
    Make sure the bound database has the current schema. Returns whether it built one.

    A no-op when the database already has tables: something else built it, and
    stamping a schema somebody else created would claim migrations ran that never did.
    """
    from sqlalchemy import inspect

    import codelith.models  # noqa: F401  — registers every table on the metadata
    from codelith.db.base import Base

    def _has_tables(conn) -> bool:
        return bool(inspect(conn).get_table_names())

    async with engine.begin() as conn:
        if await conn.run_sync(_has_tables):
            return False
        await conn.run_sync(Base.metadata.create_all)

    # Stamp *after* creating, and only when we created: stamping a database somebody
    # else built would claim migrations ran that never did.
    #
    # Off-thread because `command.stamp` loads `alembic/env.py`, which calls
    # `asyncio.run()` — and this function is already inside a loop. A thread gets its
    # own, which is the whole fix.
    import asyncio

    from alembic import command

    url = str(engine.url.render_as_string(hide_password=False))
    await asyncio.to_thread(command.stamp, _alembic_config(url), "head")

    logger.info(
        "schema_created",
        dialect=engine.dialect.name,
        tables=len(Base.metadata.tables),
    )
    return True
