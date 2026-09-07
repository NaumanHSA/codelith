"""
Bringing a database to the current schema, on the second run as well as the first.

The promise on the front page is that there is nothing to migrate. That is easy to keep
on a machine that has never run Codelith and hard to keep on one that has, which is
where this had no tests and a bug that fired on every single start.

The bug: `create_all` ran *before* `upgrade`. On a database one release behind,
`create_all` helpfully created the table the pending migration was about to create, and
then the migration died on "table already exists". The marker never advanced, so it
happened again on the next start, for ever, and no later migration could ever run.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from codelith.db.bootstrap import ensure_schema


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite+aiosqlite:///{tmp_path / 'probe.db'}"


async def _tables(engine) -> set[str]:
    from sqlalchemy import inspect

    async with engine.begin() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


async def _stamp(engine) -> list[str]:
    async with engine.begin() as conn:
        rows = await conn.execute(text("select version_num from alembic_version"))
        return [r[0] for r in rows]


def _head() -> str:
    from alembic.script import ScriptDirectory

    from codelith.db.bootstrap import _alembic_config

    return ScriptDirectory.from_config(_alembic_config("sqlite://")).get_current_head()


class TestAFreshDatabase:
    @pytest.mark.asyncio
    async def test_it_is_built_and_stamped_at_head(self, db_url):
        engine = create_async_engine(db_url)
        try:
            assert await ensure_schema(engine) is True
            assert "projects" in await _tables(engine)
            assert await _stamp(engine) == [_head()]
        finally:
            await engine.dispose()


class TestASecondStart:
    @pytest.mark.asyncio
    async def test_it_reports_it_built_nothing(self, db_url):
        engine = create_async_engine(db_url)
        try:
            await ensure_schema(engine)
            assert await ensure_schema(engine) is False
            assert await _stamp(engine) == [_head()]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_it_is_idempotent(self, db_url):
        """Three starts in a row leave the same schema and the same marker."""
        engine = create_async_engine(db_url)
        try:
            await ensure_schema(engine)
            after_first = await _tables(engine)
            await ensure_schema(engine)
            await ensure_schema(engine)
            assert await _tables(engine) == after_first
            assert await _stamp(engine) == [_head()]
        finally:
            await engine.dispose()


class TestADatabaseLeftBehindByAnEarlierRelease:
    """
    The regression that produced `schema_upgrade_failed` on every boot.

    Simulated the way it actually happens: the schema is complete, and the marker
    points at a revision before the migration that creates one of its tables.
    """

    @pytest.mark.asyncio
    async def test_a_stale_marker_is_corrected_rather_than_failing_for_ever(self, db_url, caplog):
        from alembic.script import ScriptDirectory

        from codelith.db.bootstrap import _alembic_config

        engine = create_async_engine(db_url)
        try:
            await ensure_schema(engine)

            revisions = list(
                ScriptDirectory.from_config(_alembic_config("sqlite://")).walk_revisions()
            )
            if len(revisions) < 2:
                pytest.skip("needs at least two migrations to have a 'behind' state")
            behind = revisions[1].revision  # one before head

            async with engine.begin() as conn:
                await conn.execute(text("delete from alembic_version"))
                await conn.execute(
                    text("insert into alembic_version (version_num) values (:v)"), {"v": behind}
                )

            # The schema is already complete, so the pending migration cannot run. The
            # marker is what is wrong, and the marker is what should be corrected.
            assert await ensure_schema(engine) is False
            assert await _stamp(engine) == [_head()]

            # And it stays fixed: the next start is quiet.
            assert await ensure_schema(engine) is False
            assert await _stamp(engine) == [_head()]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_a_missing_table_is_not_stamped_over(self, db_url):
        """
        The line the repair must not cross. A marker is only corrected when the schema
        genuinely matches the models; stamping past a migration that really has not
        run would guarantee it never does.
        """
        from codelith.db.bootstrap import _stamp_if_current

        engine = create_async_engine(db_url)
        try:
            await ensure_schema(engine)
            async with engine.begin() as conn:
                await conn.execute(text("drop table doc_pages"))

            sync_url = db_url.replace("+aiosqlite", "")
            assert _stamp_if_current(sync_url) is None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_a_missing_column_is_not_stamped_over(self, db_url):
        """Tables alone are not proof: a column-adding migration must still be able
        to run, so the check is on columns too."""
        from codelith.db.bootstrap import _stamp_if_current

        engine = create_async_engine(db_url)
        try:
            await ensure_schema(engine)
            # SQLite can drop a column since 3.35, which is what a "behind" schema
            # looks like from the models' point of view.
            async with engine.begin() as conn:
                await conn.execute(text("alter table projects drop column description"))

            sync_url = db_url.replace("+aiosqlite", "")
            assert _stamp_if_current(sync_url) is None
        finally:
            await engine.dispose()
