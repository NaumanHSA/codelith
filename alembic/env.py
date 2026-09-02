import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import codelith.models  # noqa: F401 — ensures all models are registered
from alembic import context
from codelith.config import get_settings
from codelith.db.base import Base

config = context.config
settings = get_settings()

# The URL comes from settings — except when a caller has already chosen one.
#
# This used to override unconditionally, which meant `Config.set_main_option` before
# invoking a command was silently ignored: a programmatic stamp aimed at a solo SQLite
# file went to the configured Postgres instead. Respecting an explicit value is what
# makes `codelith/db/bootstrap.py` able to stamp the database it just built.
if not config.attributes.get("url_set_by_caller"):
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot alter a column in place — no `SET NOT NULL`, no type change,
        # no dropping a constraint. Batch mode rewrites those as copy-and-swap, which
        # is what lets a migration written from here on run in solo mode too. It is a
        # no-op on PostgreSQL, which can alter columns directly.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
