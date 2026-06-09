from __future__ import annotations

import re
import structlog
from typing import Any

from neo4j import AsyncGraphDatabase

from app.config import get_settings

logger = structlog.get_logger(__name__)

# ── Import extractors ──────────────────────────────────────────────────────────

_PY_IMPORT_RE = re.compile(
    r'^(?:from\s+([\w./]+)\s+import|import\s+([\w., ]+))',
    re.MULTILINE,
)
_JS_IMPORT_RE = re.compile(
    r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\))""",
)


def _extract_imports(content: str, language: str) -> list[str]:
    imports: list[str] = []
    if language == "python":
        for m in _PY_IMPORT_RE.finditer(content):
            mod = (m.group(1) or m.group(2) or "").strip()
            for part in mod.split(","):
                part = part.strip().split(" ")[0]
                if part and not part.startswith("_"):
                    imports.append(part.replace(".", "/"))
    elif language in ("javascript", "typescript"):
        for m in _JS_IMPORT_RE.finditer(content):
            path = (m.group(1) or m.group(2) or "").strip()
            if path and not path.startswith("@") and not path.startswith("http"):
                imports.append(path)
    return imports


# ── GraphStore ─────────────────────────────────────────────────────────────────

class GraphStore:
    """
    Thin async wrapper around Neo4j for code entity graphs.

    Nodes: File, Function, Class
    Edges: DEFINES (File→Function/Class), IMPORTS (File→File)
    All nodes are project-scoped via project_id property.
    """

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

    # ── Graph building ─────────────────────────────────────────────────────────

    async def build_code_graph(self, project_id: int, codebase) -> dict[str, int]:
        """Build File/Function/Class nodes and IMPORTS/DEFINES edges from a ParsedCodebase."""
        if not await self.verify_connectivity():
            return {"files": 0, "symbols": 0, "imports": 0}

        files_created = symbols_created = imports_created = 0

        async with self._driver.session() as session:
            # Create constraint once (idempotent)
            await session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (f:File) REQUIRE (f.project_id, f.path) IS UNIQUE"
            )

            for pf in codebase.files:
                # File node
                await session.run(
                    "MERGE (f:File {project_id: $pid, path: $path}) SET f.language = $lang",
                    pid=project_id, path=pf.path, lang=pf.language,
                )
                files_created += 1

                # Symbol nodes
                for sym in pf.symbols:
                    label = "Class" if sym["type"] == "class" else "Function"
                    await session.run(
                        f"MERGE (s:{label} {{project_id: $pid, name: $name, file_path: $path}}) "
                        f"SET s.line = $line "
                        f"WITH s "
                        f"MATCH (f:File {{project_id: $pid, path: $path}}) "
                        f"MERGE (f)-[:DEFINES]->(s)",
                        pid=project_id, name=sym["name"],
                        path=pf.path, line=sym.get("line", 0),
                    )
                    symbols_created += 1

                # Import edges — best-effort, skip unresolvable
                imports = _extract_imports(pf.content, pf.language)
                for imp in imports[:30]:  # cap at 30 per file
                    await session.run(
                        "MATCH (src:File {project_id: $pid, path: $src_path}) "
                        "MERGE (dep:File {project_id: $pid, path: $dep_path}) "
                        "MERGE (src)-[:IMPORTS]->(dep)",
                        pid=project_id, src_path=pf.path, dep_path=imp,
                    )
                    imports_created += 1

        logger.info(
            "graph_built",
            project_id=project_id,
            files=files_created,
            symbols=symbols_created,
            imports=imports_created,
        )
        return {"files": files_created, "symbols": symbols_created, "imports": imports_created}

    # ── Queries ────────────────────────────────────────────────────────────────

    async def query(self, cypher: str, project_id: int, **params: Any) -> list[dict]:
        """Run an arbitrary Cypher query scoped to project_id."""
        if not await self.verify_connectivity():
            return []
        try:
            async with self._driver.session() as session:
                result = await session.run(cypher, project_id=project_id, **params)
                return [dict(r) for r in await result.data()]
        except Exception as exc:
            logger.warning("graph_query_failed", error=str(exc), cypher=cypher[:100])
            return []

    async def get_imports(self, project_id: int, file_path: str) -> list[str]:
        rows = await self.query(
            "MATCH (f:File {project_id: $project_id, path: $path})-[:IMPORTS]->(dep:File) "
            "RETURN dep.path AS dep",
            project_id=project_id, path=file_path,
        )
        return [r["dep"] for r in rows]

    async def get_dependents(self, project_id: int, file_path: str) -> list[str]:
        rows = await self.query(
            "MATCH (src:File {project_id: $project_id})-[:IMPORTS]->(f:File {project_id: $project_id, path: $path}) "
            "RETURN src.path AS src",
            project_id=project_id, path=file_path,
        )
        return [r["src"] for r in rows]

    async def get_module_overview(self, project_id: int, limit: int = 30) -> list[dict]:
        return await self.query(
            "MATCH (f:File {project_id: $project_id})-[:IMPORTS]->(dep:File {project_id: $project_id}) "
            "RETURN f.path AS file, collect(dep.path)[..5] AS imports, count(dep) AS import_count "
            "ORDER BY import_count DESC LIMIT $limit",
            project_id=project_id, limit=limit,
        )

    async def get_symbols(self, project_id: int, path_prefix: str = "") -> list[dict]:
        cypher = (
            "MATCH (f:File {project_id: $project_id})-[:DEFINES]->(s) "
            + ("WHERE f.path STARTS WITH $prefix " if path_prefix else "")
            + "RETURN f.path AS file, labels(s)[0] AS kind, s.name AS name, s.line AS line "
            "ORDER BY f.path, s.line LIMIT 100"
        )
        return await self.query(cypher, project_id=project_id, prefix=path_prefix)

    async def clear_project(self, project_id: int) -> None:
        if not await self.verify_connectivity():
            return
        async with self._driver.session() as session:
            await session.run(
                "MATCH (n {project_id: $pid}) DETACH DELETE n",
                pid=project_id,
            )
        logger.info("graph_cleared", project_id=project_id)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()
