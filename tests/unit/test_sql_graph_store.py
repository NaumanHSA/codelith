"""
The code graph, without a graph database.

"It works locally" is worth nothing if locally means something subtly different. What
these cases pin is that the SQL store answers the same three questions the Neo4j one
does, in the same shape and the same order — because callers do not branch on which
backing they got, and a solo user who is quietly given worse answers has no way to
find out.

Run against SQLite, which is the point: this is the backing solo mode uses, so the
recursive CTE is exercised on the database that will actually run it.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from codelith.db.base import Base
from codelith.memory.graph_store import CodeGraph, GraphScope
from codelith.memory.sql_graph_store import SqlGraphStore
from codelith.models.organization import Organization
from codelith.models.project import Project

PROJECT = 1
KB = 7


@pytest_asyncio.fixture
async def store():
    """
    A real SQLite database, in memory.

    Not mocked: the whole question is whether a recursive CTE behaves, and a fake
    would answer whatever it was told to.
    """
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add(Organization(id=1, name="o", slug="o"))
        await session.flush()
        session.add(Project(id=PROJECT, org_id=1, name="p", slug="p"))
        await session.commit()

        s = SqlGraphStore(session)
        await s.write(GraphScope(project_id=PROJECT, kb_id=KB), _graph())
        yield s

    await engine.dispose()


def _graph() -> CodeGraph:
    """
    A small import chain with a diamond, so distance is not merely a hop count.

    `routes` imports `service`, which imports `db`. `cli` also imports `db` directly.
    So `db` is reachable from `routes` at distance 2 and from `cli` at distance 1 —
    and `service` at 1. A store that reported the *longest* path, or counted the
    diamond twice, would still look plausible on a straight chain.
    """
    return CodeGraph(
        files=[
            {"path": "app/db.py", "language": "python", "module_key": "app", "loc": 10},
            {"path": "app/service.py", "language": "python", "module_key": "app", "loc": 20},
            {"path": "app/routes.py", "language": "python", "module_key": "app", "loc": 30},
            {"path": "app/cli.py", "language": "python", "module_key": "cli", "loc": 5},
        ],
        modules=[{"key": "app", "name": "app", "role": "service"}],
        symbols=[
            {"path": "app/db.py", "qname": "app.db.commit", "name": "commit",
             "kind": "function", "line": 3, "end_line": 5, "visibility": "public"},
            {"path": "app/service.py", "qname": "app.service.save", "name": "save",
             "kind": "function", "line": 8, "end_line": 12, "visibility": "public"},
        ],
        imports=[
            {"src": "app/service.py", "dst": "app/db.py"},
            {"src": "app/routes.py", "dst": "app/service.py"},
            {"src": "app/cli.py", "dst": "app/db.py"},
        ],
        packages=[{"src": "app/db.py", "name": "sqlalchemy"}],
        calls=[
            {"src_path": "app/service.py", "src_qname": "app.service.save",
             "dst_path": "app/db.py", "dst_qname": "app.db.commit"},
        ],
    )


class TestTheQuestionsTheGraphExistsFor:
    @pytest.mark.asyncio
    async def test_who_imports_this(self, store: SqlGraphStore) -> None:
        assert sorted(await store.get_dependents(PROJECT, "app/db.py")) == [
            "app/cli.py",
            "app/service.py",
        ]

    @pytest.mark.asyncio
    async def test_what_this_imports(self, store: SqlGraphStore) -> None:
        assert await store.get_imports(PROJECT, "app/service.py") == ["app/db.py"]

    @pytest.mark.asyncio
    async def test_who_calls_this(self, store: SqlGraphStore) -> None:
        assert await store.get_callers(PROJECT, "app.db.commit") == [
            {"file": "app/service.py", "caller": "app.service.save"}
        ]


class TestBlastRadius:
    @pytest.mark.asyncio
    async def test_distance_is_the_shortest_path(self, store: SqlGraphStore) -> None:
        """
        `routes` reaches `db` only through `service`, so it is two hops. `cli` and
        `service` are one. Ordering is by distance then name, matching the Cypher.
        """
        assert await store.get_blast_radius(PROJECT, "app/db.py", depth=3) == [
            {"file": "app/cli.py", "distance": 1},
            {"file": "app/service.py", "distance": 1},
            {"file": "app/routes.py", "distance": 2},
        ]

    @pytest.mark.asyncio
    async def test_depth_limits_the_walk(self, store: SqlGraphStore) -> None:
        """At one hop, the file two steps away must not appear."""
        near = await store.get_blast_radius(PROJECT, "app/db.py", depth=1)
        assert [r["file"] for r in near] == ["app/cli.py", "app/service.py"]

    @pytest.mark.asyncio
    async def test_a_leaf_has_no_radius(self, store: SqlGraphStore) -> None:
        assert await store.get_blast_radius(PROJECT, "app/routes.py") == []

    @pytest.mark.asyncio
    async def test_an_unknown_file_is_empty_not_an_error(self, store: SqlGraphStore) -> None:
        assert await store.get_blast_radius(PROJECT, "nope.py") == []


class TestScopeAndReplacement:
    @pytest.mark.asyncio
    async def test_counts_use_neo4j_labels(self, store: SqlGraphStore) -> None:
        """Callers read these keys; they must not change with the backing."""
        counts = await store.counts(PROJECT, KB)
        assert counts["File"] == 4
        assert counts["Symbol"] == 2
        assert counts["IMPORTS"] == 3
        assert counts["CALLS"] == 1
        assert counts["Package"] == counts["DEPENDS_ON"] == 1

    @pytest.mark.asyncio
    async def test_writing_again_replaces_rather_than_merges(
        self, store: SqlGraphStore
    ) -> None:
        """
        A re-analysis must not leave edges from files that have since been deleted —
        the same rule the Neo4j store holds by clearing before it writes.
        """
        smaller = CodeGraph(
            files=[{"path": "app/db.py", "language": "python", "module_key": "app", "loc": 10}],
            imports=[],
        )
        await store.write(GraphScope(project_id=PROJECT, kb_id=KB), smaller)

        assert (await store.counts(PROJECT, KB)).get("IMPORTS") is None
        assert await store.get_dependents(PROJECT, "app/db.py") == []

    @pytest.mark.asyncio
    async def test_clearing_one_knowledge_base(self, store: SqlGraphStore) -> None:
        await store.clear_kb(PROJECT, KB)
        assert await store.counts(PROJECT, KB) == {}

    @pytest.mark.asyncio
    async def test_the_scoped_readers_are_kb_specific(self, store: SqlGraphStore) -> None:
        assert len(await store.get_files(PROJECT, KB)) == 4
        assert len(await store.get_import_edges(PROJECT, KB)) == 3
        assert await store.get_packages(PROJECT, KB) == [{"name": "sqlalchemy"}]
        # A different knowledge base of the same project sees nothing.
        assert await store.get_files(PROJECT, KB + 1) == []


class TestItAnswersTheSameShape:
    @pytest.mark.asyncio
    async def test_symbols_and_overview_match_the_cypher_keys(
        self, store: SqlGraphStore
    ) -> None:
        symbols = await store.get_symbols(PROJECT)
        assert set(symbols[0]) == {"file", "kind", "name", "line"}

        overview = await store.get_module_overview(PROJECT)
        assert set(overview[0]) == {"file", "imports", "import_count"}

    @pytest.mark.asyncio
    async def test_it_needs_no_service_to_be_reachable(self, store: SqlGraphStore) -> None:
        """`GraphStore` can be unreachable; this cannot, which is the whole point."""
        assert await store.verify_connectivity() is True
