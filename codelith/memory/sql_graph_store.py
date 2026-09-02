"""
The code graph in SQL, answering the same questions as the Neo4j one.

Two of the three questions the graph exists for are a single join — who imports this
file, who calls this function. The third, "what might break if I change this", is a
transitive walk up the import edges, and that is a recursive CTE, which SQLite and
PostgreSQL have both had for years.

This is not an argument that SQL is better at graphs. It is that one person reading
one repository should not have to run a graph database to ask what calls a function,
and the shape of these three queries does not need one.

**Same answers, same order.** `tests/unit/test_sql_graph_store.py` asserts the results
against the Cypher each method replaces, because "it works locally" is worth nothing
if locally means something subtly different.
"""

from __future__ import annotations

import structlog
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.memory.graph_store import CodeGraph, GraphScope
from codelith.models.graph import (
    GraphCall,
    GraphFile,
    GraphImport,
    GraphModule,
    GraphPackage,
    GraphSymbol,
)

logger = structlog.get_logger(__name__)

#: Matches the Neo4j store's cap. A blast radius is a prompt for a person, not a
#: report, and two hundred files is already more than anybody reads.
_MAX_ROWS = 200


class SqlGraphStore:
    """The code graph over the ordinary database. Same interface as `GraphStore`."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        # A session may be handed in (inside a request) or made here (inside a task),
        # which is the same choice `GraphStore` makes about its driver.
        self._session = session
        self._owned: AsyncSession | None = None

    async def __aenter__(self) -> SqlGraphStore:
        if self._session is None:
            from codelith.db.session import AsyncSessionLocal

            self._owned = AsyncSessionLocal()
            self._session = await self._owned.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owned is not None:
            await self._owned.__aexit__(*exc)
            self._owned = None
            self._session = None

    async def close(self) -> None:
        await self.__aexit__(None, None, None)

    async def verify_connectivity(self) -> bool:
        """Always true: the graph lives in the database the application already has."""
        return True

    @property
    def db(self) -> AsyncSession:
        if self._session is None:  # pragma: no cover - defensive
            raise RuntimeError("SqlGraphStore used outside its context manager")
        return self._session

    # ── Writing ───────────────────────────────────────────────────────────────

    async def write(self, scope: GraphScope, graph: CodeGraph) -> dict[str, int]:
        """
        Replace this knowledge base's subgraph.

        Replace rather than merge, for the same reason the Neo4j store does: a
        re-analysis must not leave edges from files that have since been deleted.
        """
        await self._clear(scope.project_id, scope.kb_id)
        key = {"project_id": scope.project_id, "kb_id": scope.kb_id}

        rows: list = []
        rows += [GraphFile(**key, **_pick(f, "path", "language", "module_key", "loc")) for f in graph.files]
        rows += [GraphModule(**key, **_pick(m, "key", "name", "role")) for m in graph.modules]
        rows += [
            GraphSymbol(
                **key,
                **_pick(s, "path", "qname", "name", "kind", "line", "end_line", "visibility"),
            )
            for s in graph.symbols
        ]
        rows += [GraphImport(**key, **_pick(i, "src", "dst")) for i in graph.imports]
        rows += [GraphPackage(**key, **_pick(p, "src", "name")) for p in graph.packages]
        rows += [
            GraphCall(**key, **_pick(c, "src_path", "src_qname", "dst_path", "dst_qname"))
            for c in graph.calls
        ]

        self.db.add_all(rows)
        await self.db.commit()

        counts = graph.counts()
        logger.info("graph_written", backend="sql", **key, **counts)
        return counts

    async def _clear(self, project_id: int, kb_id: int | None) -> None:
        for model in (GraphFile, GraphModule, GraphSymbol, GraphImport, GraphPackage, GraphCall):
            stmt = delete(model).where(model.project_id == project_id)
            if kb_id is not None:
                stmt = stmt.where(model.kb_id == kb_id)
            await self.db.execute(stmt)
        await self.db.commit()

    async def clear_kb(self, project_id: int, kb_id: int) -> None:
        await self._clear(project_id, kb_id)

    async def clear_project(self, project_id: int) -> None:
        await self._clear(project_id, None)

    # ── Reading ───────────────────────────────────────────────────────────────

    async def counts(self, project_id: int, kb_id: int | None = None) -> dict[str, int]:
        """
        Totals under the same labels Neo4j reports, so callers do not branch.

        `File`, `Module`, `Symbol` and `Package` are node labels there; `IMPORTS`,
        `DEPENDS_ON` and `CALLS` are relationship types. Only non-zero entries are
        returned, which is also what the Cypher does.
        """
        labels = {
            "File": GraphFile,
            "Module": GraphModule,
            "Symbol": GraphSymbol,
            "Package": GraphPackage,
            "IMPORTS": GraphImport,
            "CALLS": GraphCall,
        }
        out: dict[str, int] = {}
        for label, model in labels.items():
            stmt = select(func.count()).select_from(model).where(model.project_id == project_id)
            if kb_id is not None:
                stmt = stmt.where(model.kb_id == kb_id)
            n = (await self.db.execute(stmt)).scalar() or 0
            if n:
                out[label] = n
        # A package row is both the node and the edge to it in Neo4j's shape.
        if "Package" in out:
            out["DEPENDS_ON"] = out["Package"]
        return out

    async def get_imports(self, project_id: int, file_path: str) -> list[str]:
        rows = await self.db.execute(
            select(GraphImport.dst)
            .where(GraphImport.project_id == project_id, GraphImport.src == file_path)
            .distinct()
        )
        return [r[0] for r in rows]

    async def get_dependents(self, project_id: int, file_path: str) -> list[str]:
        """Who imports this file — the first question impact analysis asks."""
        rows = await self.db.execute(
            select(GraphImport.src)
            .where(GraphImport.project_id == project_id, GraphImport.dst == file_path)
            .distinct()
        )
        return [r[0] for r in rows]

    async def get_blast_radius(
        self, project_id: int, file_path: str, depth: int = 3
    ) -> list[dict]:
        """
        Files that transitively import this one, with their distance.

        A recursive CTE walking import edges backwards. Depth is clamped to 1..6 as
        the Cypher clamps its variable-length pattern: an unbounded walk of a large
        import graph does not come back, and nobody reads past three hops anyway.

        `distance` is the *shortest* path, which is why the outer query groups — the
        same file is commonly reachable at several depths and the nearest is the one
        that matters.
        """
        limit = max(1, min(depth, 6))
        sql = text(
            """
            WITH RECURSIVE reach(path, distance) AS (
                SELECT src, 1 FROM graph_imports
                 WHERE project_id = :pid AND dst = :path
                UNION ALL
                SELECT i.src, r.distance + 1
                  FROM graph_imports i
                  JOIN reach r ON i.dst = r.path
                 WHERE i.project_id = :pid AND r.distance < :depth
            )
            SELECT path AS file, MIN(distance) AS distance
              FROM reach
             GROUP BY path
             ORDER BY distance, file
             LIMIT :cap
            """
        )
        rows = await self.db.execute(
            sql, {"pid": project_id, "path": file_path, "depth": limit, "cap": _MAX_ROWS}
        )
        return [{"file": r.file, "distance": r.distance} for r in rows]

    async def get_module_overview(self, project_id: int, limit: int = 30) -> list[dict]:
        """Files with the most imports, and a sample of what they pull in."""
        counted = (
            select(GraphImport.src, func.count().label("n"))
            .where(GraphImport.project_id == project_id)
            .group_by(GraphImport.src)
            .order_by(func.count().desc())
            .limit(limit)
        )
        out: list[dict] = []
        for src, n in await self.db.execute(counted):
            sample = await self.db.execute(
                select(GraphImport.dst)
                .where(GraphImport.project_id == project_id, GraphImport.src == src)
                .limit(5)
            )
            out.append({"file": src, "imports": [r[0] for r in sample], "import_count": n})
        return out

    async def get_symbols(self, project_id: int, path_prefix: str = "") -> list[dict]:
        stmt = select(
            GraphSymbol.path, GraphSymbol.kind, GraphSymbol.name, GraphSymbol.line
        ).where(GraphSymbol.project_id == project_id)
        if path_prefix:
            stmt = stmt.where(GraphSymbol.path.startswith(path_prefix))
        stmt = stmt.order_by(GraphSymbol.path, GraphSymbol.line).limit(100)
        return [
            {"file": p, "kind": k, "name": n, "line": ln}
            for p, k, n, ln in await self.db.execute(stmt)
        ]

    async def get_callers(self, project_id: int, qname: str) -> list[dict]:
        stmt = (
            select(GraphCall.src_path, GraphCall.src_qname)
            .where(GraphCall.project_id == project_id, GraphCall.dst_qname == qname)
            .distinct()
            .order_by(GraphCall.src_path)
            .limit(100)
        )
        return [{"file": p, "caller": q} for p, q in await self.db.execute(stmt)]

    async def get_files(self, project_id: int, kb_id: int) -> list[dict]:
        stmt = select(GraphFile.path, GraphFile.module_key).where(
            GraphFile.project_id == project_id, GraphFile.kb_id == kb_id
        )
        return [{"path": p, "module_key": m} for p, m in await self.db.execute(stmt)]

    async def get_import_edges(self, project_id: int, kb_id: int) -> list[dict]:
        stmt = select(GraphImport.src, GraphImport.dst).where(
            GraphImport.project_id == project_id, GraphImport.kb_id == kb_id
        )
        return [{"src": s, "dst": d} for s, d in await self.db.execute(stmt)]

    async def get_packages(self, project_id: int, kb_id: int) -> list[dict]:
        stmt = (
            select(GraphPackage.name)
            .where(GraphPackage.project_id == project_id, GraphPackage.kb_id == kb_id)
            .distinct()
        )
        return [{"name": n} for (n,) in await self.db.execute(stmt)]


def _pick(row: dict, *keys: str) -> dict:
    """The named keys that are present — provider output is not uniformly shaped."""
    return {k: row.get(k) for k in keys}
