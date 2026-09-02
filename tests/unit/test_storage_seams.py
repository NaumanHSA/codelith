"""
The services that are gone, and stay gone.

Codelith used to run on Postgres, Redis, Neo4j and MinIO with a Celery worker beside
it — six containers before anybody could try it. All of that was replaced by a SQLite
file, a folder, a set in memory and a background thread, and then deleted.

This is what stops it coming back. Each of these libraries is easy to reach for and
individually reasonable in review: an import of `redis` for a cache, of `boto3` for
one upload. The second one is what turns "runs anywhere with Python" back into "and
here are the containers you need first", and nobody notices until somebody tries to
install it.

The rule is a test rather than a note, for the same reason `test_module_isolation.py`
is one: conventions decay silently.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "codelith"

#: Removed along with the second way of running this. Each was one module; each is
#: now nothing.
REMOVED = ("neo4j", "boto3", "redis", "celery", "asyncpg", "pgvector")

#: Cypher clause keywords. The code graph is SQL now, so any of these means a
#: Neo4j-shaped query written against a database that does not speak it.
_CYPHER = re.compile(r"\b(MATCH \(|UNWIND \$|MERGE \(|DETACH DELETE)\b")


def _python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _rel(path: Path) -> str:
    return path.relative_to(APP).as_posix()


def _imported_roots(path: Path) -> set[str]:
    """Top-level packages this file imports, parsed rather than grepped."""
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


class TestTheServicesAreGone:
    @pytest.mark.parametrize("library", REMOVED)
    def test_nothing_imports_it(self, library: str) -> None:
        offenders = [_rel(f) for f in _python_files(APP) if library in _imported_roots(f)]
        assert not offenders, (
            f"`{library}` is back, in:\n  "
            + "\n  ".join(offenders)
            + "\nCodelith runs with nothing installed. Reaching for this puts a "
            "container back between somebody and trying it."
        )

    @pytest.mark.parametrize("library", REMOVED)
    def test_it_is_not_a_dependency_either(self, library: str) -> None:
        """An unused dependency is still installed, and is still an invitation."""
        pyproject = (APP.parent / "pyproject.toml").read_text(encoding="utf-8")
        declared = [
            line.strip()
            for line in pyproject.splitlines()
            if line.strip().startswith(f'"{library}')
        ]
        assert not declared, f"{library} is still declared: {declared}"


class TestCypherIsGone:
    def test_no_module_writes_cypher(self) -> None:
        offenders = [
            _rel(f) for f in _python_files(APP) if _CYPHER.search(f.read_text(encoding="utf-8"))
        ]
        assert not offenders, "Cypher found in:\n  " + "\n  ".join(offenders)


class TestThereIsOnlyOneWayToRun:
    def test_there_is_no_profile_setting(self) -> None:
        """
        There was a `CODELITH_PROFILE` choosing between two sets of implementations.
        One mode means no setting: a knob with one position is a knob somebody
        eventually turns.
        """
        from codelith.config import get_settings

        assert not hasattr(get_settings(), "CODELITH_PROFILE")

    def test_the_database_needs_nothing_installed(self) -> None:
        from codelith.config import get_settings

        assert get_settings().DATABASE_URL.startswith("sqlite")

    @pytest.mark.parametrize(
        "setting",
        ["REDIS_URL", "CELERY_BROKER_URL", "NEO4J_URI", "S3_BUCKET_NAME", "POSTGRES_HOST"],
    )
    def test_the_settings_for_them_are_gone_too(self, setting: str) -> None:
        """A setting for a service nobody runs is a promise that cannot be kept."""
        from codelith.config import get_settings

        assert not hasattr(get_settings(), setting)
