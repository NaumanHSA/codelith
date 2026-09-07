"""
Getting a database to the current schema without running a migration.

The database is a file this process owns. On a machine that has never run Codelith it
does not exist, and an empty one is indistinguishable from a first launch — so the
schema is built from the models and the chain stamped as applied. There is no separate
migrate step to forget.

**Existing databases get missing tables too**, which they did not before, and the gap
was real: a new release that adds a table left every already-installed copy without it,
because this returned early the moment it saw any table at all. The promise on the
front page is that there is nothing to migrate; that has to hold on the second run as
well as the first. `create_all` is additive — it creates what is absent and touches
nothing that exists — so this is safe to run every time.

`create_all` cannot alter a table that has changed shape, though, so the migrations are
then applied as well. That is what makes "there is no migrate step" true rather than
nearly true: adding a table and adding a column are the same event to somebody
installing a new version, and only one of them used to work. The database is a file
this process owns, so running its own migrations is not a liberty — it is the only
thing that could.

It also repairs an unresolvable stamp. Fourteen migrations were squashed into one
baseline, which left every database created before that pointing at a revision no
longer in the chain — and alembic refuses to do anything at all in that state, so
`upgrade` and `revision --autogenerate` both fail with "Can't locate revision". The
schema is right; only the marker is wrong, so the marker is what gets corrected.
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
        existed = await conn.run_sync(_has_tables)

    # Off-thread because `command.stamp` loads `alembic/env.py`, which calls
    # `asyncio.run()` — and this function is already inside a loop. A thread gets its
    # own, which is the whole fix.
    import asyncio

    from alembic import command

    url = str(engine.url.render_as_string(hide_password=False))

    if not existed:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await asyncio.to_thread(command.stamp, _alembic_config(url), "head")
        logger.info(
            "schema_created",
            dialect=engine.dialect.name,
            tables=len(Base.metadata.tables),
        )
        return True

    if repaired := await asyncio.to_thread(_repair_stamp, url):
        logger.warning(
            "schema_version_repaired",
            now=repaired,
            hint="the recorded revision was squashed away; the marker was corrected",
        )

    # **Migrations before `create_all`, and the order is the whole point.**
    #
    # It used to be the other way round, and that made every table-creating migration
    # fail for ever. `create_all` is additive, so on a database one release behind it
    # helpfully created the new table; then `upgrade` ran the migration that creates
    # that same table and died on "table already exists". The marker never advanced,
    # so it failed again on the next start, and the next, and no later migration could
    # ever run. Applying migrations first lets them do their own work, and leaves
    # `create_all` doing only what it is good at.
    failure: Exception | None = None
    try:
        await asyncio.to_thread(command.upgrade, _alembic_config(url), "head")
    except Exception as exc:
        failure = exc

    # Tables no migration ever introduced, which is the case this exists for: a model
    # added without one. Additive, so it touches nothing that already exists.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if failure is not None:
        # A database left in the broken state above still has to recover, and by this
        # point it can: every table is present, so the schema really is at head and
        # only the marker disagrees. Same reasoning as `_repair_stamp`, different
        # cause. Checked against the models rather than assumed, because stamping past
        # a migration that genuinely has not run would hide a missing column.
        if stamped := await asyncio.to_thread(_stamp_if_current, url):
            logger.warning(
                "schema_version_advanced",
                now=stamped,
                error=str(failure),
                hint="the schema already matched the models; the stale marker was corrected",
            )
        else:
            logger.error(
                "schema_upgrade_failed",
                error=str(failure),
                hint="run `alembic upgrade head` by hand; some features will misbehave",
            )
    return False


def _repair_stamp(url: str) -> str | None:
    """
    Correct a version marker pointing at a revision that no longer exists.

    Returns the revision written, or `None` when there was nothing to fix.

    The row is written directly rather than through `command.stamp`, and that is the
    whole point: `stamp` resolves the *current* revision before setting a new one, so
    on exactly the database this exists to rescue it fails with the same "Can't locate
    revision" as every other alembic command. There is nothing to resolve — the
    schema is already correct and only the marker is wrong.

    Silent about every other failure. A database whose marker cannot be read is not a
    reason to refuse to start; the next real migration will complain loudly enough,
    and by then somebody is looking.
    """
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text

    try:
        scripts = ScriptDirectory.from_config(_alembic_config(url))
        known = {rev.revision for rev in scripts.walk_revisions()}
        head = scripts.get_current_head()
    except Exception:  # pragma: no cover - a broken chain is not this function's job
        return None
    if not head:
        return None

    # A sync engine: this runs on a worker thread, off the event loop.
    sync_url = url.replace("+aiosqlite", "").replace("+asyncpg", "")
    try:
        engine = create_engine(sync_url)
        with engine.begin() as conn:
            rows = conn.execute(text("select version_num from alembic_version")).scalars().all()
            if not rows or set(rows) & known:
                return None
            conn.execute(text("delete from alembic_version"))
            conn.execute(
                text("insert into alembic_version (version_num) values (:v)"), {"v": head}
            )
        engine.dispose()
        return head
    except Exception:
        # No version table yet, or a database that will not answer. Neither is worth
        # failing a startup over.
        return None



def _stamp_if_current(url: str) -> str | None:
    """
    Write the head revision, but only if the live schema already matches the models.

    Returns the revision written, or `None` when it did not qualify.

    The narrow case this is for: `upgrade` failed because a migration tried to create
    a table that was already there, so the schema is at head and the marker is behind.
    Stamping unconditionally would be wrong, because the same failure could equally
    mean a column-adding migration has not run, and a marker that says "done" would
    make sure it never did. So every table *and every column* the models declare is
    checked first, and anything missing means no stamp and the loud error instead.
    """
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect, text

    import codelith.models  # noqa: F401  — registers every table on the metadata
    from codelith.db.base import Base

    try:
        head = ScriptDirectory.from_config(_alembic_config(url)).get_current_head()
    except Exception:  # pragma: no cover - a broken chain is not this function's job
        return None
    if not head:
        return None

    sync_url = url.replace("+aiosqlite", "").replace("+asyncpg", "")
    try:
        engine = create_engine(sync_url)
        with engine.begin() as conn:
            inspector = inspect(conn)
            present = set(inspector.get_table_names())
            for name, table in Base.metadata.tables.items():
                if name not in present:
                    return None
                columns = {c["name"] for c in inspector.get_columns(name)}
                if not {c.name for c in table.columns} <= columns:
                    return None

            conn.execute(text("delete from alembic_version"))
            conn.execute(text("insert into alembic_version (version_num) values (:v)"), {"v": head})
        engine.dispose()
        return head
    except Exception:
        # Same posture as `_repair_stamp`: a database that will not answer is not a
        # reason to refuse to start, and the caller logs the original failure anyway.
        return None
