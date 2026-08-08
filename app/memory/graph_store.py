"""
The code graph: what imports what, what defines what, what calls what.

This is the half of code comprehension that vector search cannot do. *"Which files
reach `session.commit`"* and *"what breaks if I change this"* are traversals, not
similarities — no embedding of a function body encodes its callers.

Three rules this module exists to hold:

* **Nothing language-specific lives here.** Imports arrive already extracted and
  already resolved, because turning `from .. import session` into a path requires
  knowing the language's rules. `LanguageProvider.resolve_import` owns that; this
  file would otherwise grow the `if language == "python"` branch the architecture
  forbids.
* **A node is only created for something that exists.** The previous implementation
  did `MERGE (dep:File {path: $dep_path})` on every import target, which minted File
  nodes for `os`, `json` and every third-party package — a graph mostly composed of
  files that are not in the repository. External targets are `Package` nodes, and
  unresolvable ones are dropped.
* **Writes are batched.** One `session.run` per symbol is 3,244 round trips for a
  medium repository. Everything here goes through `UNWIND`.

Scoped by `kb_id`, not just `project_id`: a knowledge base is pinned to a commit, and
two analyses of the same repository at different commits must not merge into one
graph. Deleting a KB deletes its subgraph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog
from neo4j import AsyncGraphDatabase

from app.config import get_settings

logger = structlog.get_logger(__name__)

#: Rows per `UNWIND`. Large enough that round trips stop mattering, small enough that
#: a single transaction stays well inside Neo4j's heap on a laptop.
_BATCH = 500


@dataclass(frozen=True, slots=True)
class GraphScope:
    """Which analysis a subgraph belongs to."""

    project_id: int
    kb_id: int | None = None
    commit_sha: str | None = None


@dataclass(slots=True)
class CodeGraph:
    """
    The graph as plain data, before it touches a database.

    Assembled by the graph builder from provider output, so it can be asserted about
    in tests without Neo4j running — which is most of what there is to get wrong.
    """

    #: {path, language, module_key, loc}
    files: list[dict] = field(default_factory=list)
    #: {key, name, role}
    modules: list[dict] = field(default_factory=list)
    #: {path, qname, name, kind, line, end_line, visibility}
    symbols: list[dict] = field(default_factory=list)
    #: {src, dst} — both repository paths
    imports: list[dict] = field(default_factory=list)
    #: {src, name} — a file and the external package it depends on
    packages: list[dict] = field(default_factory=list)
    #: {src_path, src_qname, dst_path, dst_qname}
    calls: list[dict] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "files": len(self.files),
            "modules": len(self.modules),
            "symbols": len(self.symbols),
            "imports": len(self.imports),
            "packages": len(self.packages),
            "calls": len(self.calls),
        }


class GraphStore:
    """Async Neo4j wrapper for the code graph."""

    def __init__(self) -> None:
        settings = get_settings()
        self._driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )

    async def close(self) -> None:
        await self._driver.close()

    async def verify_connectivity(self) -> bool:
        try:
            await self._driver.verify_connectivity()
            return True
        except Exception as exc:
            logger.warning("neo4j_unreachable", error=str(exc))
            return False

    # ── Writing ───────────────────────────────────────────────────────────────

    async def write(self, scope: GraphScope, graph: CodeGraph) -> dict[str, int]:
        """
        Replace this KB's subgraph with `graph`.

        Returns what was written, so the caller can record it in `stats_json` and a
        run that silently produced nothing is visible rather than assumed fine.
        """
        if not await self.verify_connectivity():
            logger.warning("graph_write_skipped", reason="neo4j unreachable")
            return {"written": 0}

        key = {"pid": scope.project_id, "kb": scope.kb_id, "sha": scope.commit_sha}

        async with self._driver.session() as session:
            await self._ensure_constraints(session)
            # Replace rather than merge: a re-analysis of the same KB must not leave
            # edges from files that have since been deleted.
            await self._clear(session, scope)

            await self._run_batched(
                session,
                "UNWIND $rows AS r "
                "CREATE (f:File {project_id: $pid, kb_id: $kb, commit_sha: $sha, "
                "path: r.path, language: r.language, module_key: r.module_key, loc: r.loc})",
                graph.files, key,
            )
            await self._run_batched(
                session,
                "UNWIND $rows AS r "
                "CREATE (m:Module {project_id: $pid, kb_id: $kb, "
                "key: r.key, name: r.name, role: r.role})",
                graph.modules, key,
            )
            await self._run_batched(
                session,
                "UNWIND $rows AS r "
                "MATCH (m:Module {project_id: $pid, kb_id: $kb, key: r.module_key}) "
                "MATCH (f:File {project_id: $pid, kb_id: $kb, path: r.path}) "
                "CREATE (m)-[:CONTAINS]->(f)",
                [f for f in graph.files if f.get("module_key")], key,
            )
            await self._run_batched(
                session,
                "UNWIND $rows AS r "
                "MATCH (f:File {project_id: $pid, kb_id: $kb, path: r.path}) "
                "CREATE (s:Symbol {project_id: $pid, kb_id: $kb, path: r.path, "
                "qname: r.qname, name: r.name, kind: r.kind, line: r.line, "
                "end_line: r.end_line, visibility: r.visibility}) "
                "CREATE (f)-[:DEFINES]->(s)",
                graph.symbols, key,
            )
            await self._run_batched(
                session,
                "UNWIND $rows AS r "
                "MATCH (a:File {project_id: $pid, kb_id: $kb, path: r.src}) "
                "MATCH (b:File {project_id: $pid, kb_id: $kb, path: r.dst}) "
                "MERGE (a)-[:IMPORTS]->(b)",
                graph.imports, key,
            )
            await self._run_batched(
                session,
                "UNWIND $rows AS r "
                "MATCH (f:File {project_id: $pid, kb_id: $kb, path: r.src}) "
                "MERGE (p:Package {project_id: $pid, kb_id: $kb, name: r.name}) "
                "MERGE (f)-[:DEPENDS_ON]->(p)",
                graph.packages, key,
            )
            await self._run_batched(
                session,
                "UNWIND $rows AS r "
                "MATCH (a:Symbol {project_id: $pid, kb_id: $kb, path: r.src_path, qname: r.src_qname}) "
                "MATCH (b:Symbol {project_id: $pid, kb_id: $kb, path: r.dst_path, qname: r.dst_qname}) "
                "MERGE (a)-[:CALLS]->(b)",
                graph.calls, key,
            )

        counts = graph.counts()
        logger.info("graph_written", project_id=scope.project_id, kb_id=scope.kb_id, **counts)
        return counts

    @staticmethod
    async def _run_batched(session, cypher: str, rows: list[dict], key: dict) -> None:
        for start in range(0, len(rows), _BATCH):
            await session.run(cypher, rows=rows[start : start + _BATCH], **key)

    @staticmethod
    async def _ensure_constraints(session) -> None:
        for stmt in (
            "CREATE CONSTRAINT file_key IF NOT EXISTS FOR (f:File) "
            "REQUIRE (f.project_id, f.kb_id, f.path) IS UNIQUE",
            "CREATE CONSTRAINT module_key IF NOT EXISTS FOR (m:Module) "
            "REQUIRE (m.project_id, m.kb_id, m.key) IS UNIQUE",
            "CREATE CONSTRAINT package_key IF NOT EXISTS FOR (p:Package) "
            "REQUIRE (p.project_id, p.kb_id, p.name) IS UNIQUE",
            # Symbols are deliberately not unique: overloads and re-definitions of a
            # name in one file are legal, and refusing to store the second is worse
            # than storing both.
            "CREATE INDEX symbol_key IF NOT EXISTS FOR (s:Symbol) "
            "ON (s.project_id, s.kb_id, s.path, s.qname)",
        ):
            try:
                await session.run(stmt)
            except Exception as exc:  # pragma: no cover - older Neo4j, different syntax
                logger.debug("graph_constraint_skipped", error=str(exc))

    @staticmethod
    async def _clear(session, scope: GraphScope) -> None:
        if scope.kb_id is not None:
            await session.run(
                "MATCH (n {project_id: $pid, kb_id: $kb}) DETACH DELETE n",
                pid=scope.project_id, kb=scope.kb_id,
            )
        else:
            await session.run(
                "MATCH (n {project_id: $pid}) DETACH DELETE n", pid=scope.project_id
            )

    async def clear_kb(self, project_id: int, kb_id: int) -> None:
        """Drop one KB's subgraph. Called when the knowledge base is deleted."""
        if not await self.verify_connectivity():
            return
        async with self._driver.session() as session:
            await self._clear(session, GraphScope(project_id, kb_id))
        logger.info("graph_cleared", project_id=project_id, kb_id=kb_id)

    async def clear_project(self, project_id: int) -> None:
        if not await self.verify_connectivity():
            return
        async with self._driver.session() as session:
            await self._clear(session, GraphScope(project_id))
        logger.info("graph_cleared", project_id=project_id)

    # ── Queries ───────────────────────────────────────────────────────────────

    async def query(self, cypher: str, project_id: int, **params: Any) -> list[dict]:
        """Run Cypher scoped to a project. Returns [] rather than raising."""
        if not await self.verify_connectivity():
            return []
        try:
            async with self._driver.session() as session:
                result = await session.run(cypher, project_id=project_id, **params)
                return [dict(r) for r in await result.data()]
        except Exception as exc:
            logger.warning("graph_query_failed", error=str(exc), cypher=cypher[:100])
            return []

    async def counts(self, project_id: int, kb_id: int | None = None) -> dict[str, int]:
        """Node and edge totals — the measurement K1 is judged by."""
        scope = "n.kb_id = $kb_id AND " if kb_id is not None else ""
        nodes = await self.query(
            f"MATCH (n) WHERE {scope}n.project_id = $project_id "
            "RETURN labels(n)[0] AS label, count(*) AS n",
            project_id=project_id, **({"kb_id": kb_id} if kb_id is not None else {}),
        )
        edges = await self.query(
            f"MATCH (n)-[r]->() WHERE {scope}n.project_id = $project_id "
            "RETURN type(r) AS label, count(*) AS n",
            project_id=project_id, **({"kb_id": kb_id} if kb_id is not None else {}),
        )
        return {r["label"]: r["n"] for r in [*nodes, *edges] if r.get("label")}

    async def get_imports(self, project_id: int, file_path: str) -> list[str]:
        rows = await self.query(
            "MATCH (f:File {project_id: $project_id, path: $path})-[:IMPORTS]->(dep:File) "
            "RETURN DISTINCT dep.path AS dep",
            project_id=project_id, path=file_path,
        )
        return [r["dep"] for r in rows]

    async def get_dependents(self, project_id: int, file_path: str) -> list[str]:
        """Who imports this file — the first question impact analysis asks."""
        rows = await self.query(
            "MATCH (src:File {project_id: $project_id})-[:IMPORTS]->"
            "(f:File {project_id: $project_id, path: $path}) "
            "RETURN DISTINCT src.path AS src",
            project_id=project_id, path=file_path,
        )
        return [r["src"] for r in rows]

    async def get_blast_radius(
        self, project_id: int, file_path: str, depth: int = 3
    ) -> list[dict]:
        """
        Files that transitively import this one, with their distance.

        Approximate by construction — see the module docstring. Presented as "might be
        affected", never as a complete list.
        """
        return await self.query(
            "MATCH path = (src:File {project_id: $project_id})-[:IMPORTS*1..%d]->"
            "(f:File {project_id: $project_id, path: $path}) "
            "RETURN DISTINCT src.path AS file, min(length(path)) AS distance "
            "ORDER BY distance, file LIMIT 200" % max(1, min(depth, 6)),
            project_id=project_id, path=file_path,
        )

    async def get_module_overview(self, project_id: int, limit: int = 30) -> list[dict]:
        return await self.query(
            "MATCH (f:File {project_id: $project_id})-[:IMPORTS]->(dep:File {project_id: $project_id}) "
            "RETURN f.path AS file, collect(dep.path)[..5] AS imports, count(dep) AS import_count "
            "ORDER BY import_count DESC LIMIT $limit",
            project_id=project_id, limit=limit,
        )

    async def get_symbols(self, project_id: int, path_prefix: str = "") -> list[dict]:
        cypher = (
            "MATCH (f:File {project_id: $project_id})-[:DEFINES]->(s:Symbol) "
            + ("WHERE f.path STARTS WITH $prefix " if path_prefix else "")
            + "RETURN f.path AS file, s.kind AS kind, s.name AS name, s.line AS line "
            "ORDER BY f.path, s.line LIMIT 100"
        )
        return await self.query(cypher, project_id=project_id, prefix=path_prefix)

    async def get_callers(self, project_id: int, qname: str) -> list[dict]:
        rows = await self.query(
            "MATCH (a:Symbol {project_id: $project_id})-[:CALLS]->"
            "(b:Symbol {project_id: $project_id, qname: $qname}) "
            "RETURN DISTINCT a.path AS file, a.qname AS caller ORDER BY file LIMIT 100",
            project_id=project_id, qname=qname,
        )
        return rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()


__all__ = ["GraphStore", "GraphScope", "CodeGraph"]
