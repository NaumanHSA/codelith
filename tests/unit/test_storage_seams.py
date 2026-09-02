"""
One module per external service, and the query language stays inside it.

Solo mode — one person, one machine, no containers — is a substitution behind a few
seams rather than a rewrite, and that is only true for as long as each service has
exactly one door. Today it does: Neo4j is imported by one file, boto3 by one, redis by
one, Celery by one. Nothing enforced that; it was a happy consequence of "all DB
access goes through repositories" and a graph builder written as a pure function.

A happy consequence is not a guarantee. The second file to `import boto3` is the one
that makes filesystem storage a refactor instead of a swap, and it will look entirely
reasonable in review — it always does. So the rule is a test, like
`test_module_isolation.py`, and for the same reason: conventions decay silently.

The Cypher rule is the same rule one level down. Three call sites outside the graph
store used to run raw Cypher — a diagram agent and the grounding code — which made the
graph the one storage engine whose query language had leaked into agents. An interface
you cannot reimplement is not an interface.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "codelith"

#: The external service, and the single module allowed to speak to it.
#:
#: Each of these is a seam solo mode replaces: a graph in SQL, a directory instead of a
#: bucket, an in-process flag instead of Redis, a coroutine instead of a task queue.
SEAMS: dict[str, str] = {
    "neo4j": "memory/graph_store.py",
    "boto3": "storage/s3.py",
    "redis": "core/cancellation.py",
    "celery": "workers/celery_app.py",
}

#: Cypher is Neo4j's language and belongs behind its door. Matched on clause keywords
#: that do not otherwise appear in Python at the start of a string.
_CYPHER = re.compile(r"\b(MATCH \(|UNWIND \$|MERGE \(|DETACH DELETE)\b")

#: Files that legitimately dispatch Celery tasks. A task is queued from the composition
#: root that knows what kind of work it is, which is a different thing from importing
#: Celery itself — these name `.delay()`, not the library.
_TASK_DISPATCHERS = "apps/", "api/v1/", "services/", "workers/"


def _python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _rel(path: Path) -> str:
    return path.relative_to(APP).as_posix()


def _imported_roots(path: Path) -> set[str]:
    """Top-level package names this file imports, parsed rather than grepped."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
        return set()

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module.split(".")[0])
    return found


class TestEachServiceHasOneDoor:
    @pytest.mark.parametrize("library,owner", sorted(SEAMS.items()))
    def test_only_its_own_module_imports_it(self, library: str, owner: str) -> None:
        offenders = [
            _rel(f)
            for f in _python_files(APP)
            if _rel(f) != owner and library in _imported_roots(f)
        ]
        assert not offenders, (
            f"`{library}` is imported outside {owner}:\n  " + "\n  ".join(offenders) + "\n"
            f"Solo mode replaces {owner}. A second importer makes that a refactor "
            "rather than a swap — put what you need behind the seam instead."
        )

    def test_every_named_owner_exists(self) -> None:
        """
        A seam whose owner has been moved or renamed silently stops being enforced,
        and the test keeps passing because nothing imports a file that is not there.
        """
        for library, owner in SEAMS.items():
            assert (APP / owner).exists(), f"{owner} is gone — who owns {library} now?"


class TestCypherStaysBehindTheGraphStore:
    def test_no_agent_writes_cypher(self) -> None:
        owner = SEAMS["neo4j"]
        offenders = []
        for f in _python_files(APP):
            if _rel(f) == owner:
                continue
            if _CYPHER.search(f.read_text(encoding="utf-8")):
                offenders.append(_rel(f))

        assert not offenders, (
            "Cypher outside the graph store:\n  " + "\n  ".join(offenders) + "\n"
            "Add a named method to `GraphStore` instead. An interface that callers "
            "bypass with raw queries cannot be implemented by anything else."
        )

    def test_the_store_still_offers_what_those_callers_needed(self) -> None:
        """
        The three methods that replaced raw queries. Named here so that deleting one
        fails loudly rather than sending somebody back to `query()`.
        """
        from codelith.memory.graph_store import GraphStore

        for method in ("get_files", "get_import_edges", "get_packages"):
            assert callable(getattr(GraphStore, method, None)), (
                f"`GraphStore.{method}` is gone. It exists because a caller outside "
                "this module needed it without writing Cypher."
            )
