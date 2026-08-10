"""
The rule that keeps the base from becoming shaped like its newest feature.

The repository was built documentation-first and the shape stuck: analysis read as a
step toward producing a document, and a day went into undoing that. The way it happens
again is gradually — one import at a time, each individually reasonable — so the rule
is a test rather than a convention.

**Two directions, both enforced here:**

1. The base may not import a feature. The moment `app/knowledge/` knows what
   documentation is, the knowledge base is documentation-shaped again.
2. A feature may not import another feature. If two need the same thing, it belongs in
   the base — otherwise the isolation is a diamond wearing a folder structure.

Conventions decay silently. Four call sites once decided independently whether a
knowledge base was usable and one had drifted, so the same project offered a feature on
one screen and refused it on another, and nothing failed loudly enough to notice.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"

#: Packages that are the base. A feature reads these; they must never read back.
#:
#: Not simply "everything outside app/features": the composition root has to wire the
#: features in somewhere, and pretending otherwise would mean either a fake exception
#: or an app that cannot serve them.
BASE_PACKAGES = (
    "knowledge",
    "languages",
    "memory",
    "llm",
    "db",
    "models",
    "core",
    "schemas",
    "ingestion",
    "storage",
    "tools",
    "tracing",
    "formatters",
)

#: Where features are allowed to be named from outside them. Each is a composition
#: root — a place whose job is assembling the application out of its parts.
WIRING_POINTS = {
    "api/v1/router.py",       # mounts each feature's routes
    "workers/celery_app.py",  # lists each feature's task modules
    "features/registry.py",   # declares what exists
    "api/v1/features.py",     # serves the registry
    "api/v1/projects.py",     # per-project feature availability
    "main.py",
}


def _imports(path: Path) -> set[str]:
    """Every module named by an `import` in this file, including local ones.

    Parsed rather than grepped: a comment mentioning `app.features` is not an import,
    and this test is about what the code actually does.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
        return set()

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def _python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _rel(path: Path) -> str:
    return path.relative_to(APP).as_posix()


def _feature_of(path: Path) -> str | None:
    """Which feature a file belongs to, or None if it is not in one."""
    parts = path.relative_to(APP).parts
    return parts[1] if len(parts) > 2 and parts[0] == "features" else None


class TestTheBaseDoesNotKnowAboutFeatures:
    """
    Direction 1. `app/knowledge/` is the substrate every feature reads; if it imports
    one, the substrate has a favourite and the next feature has to fit around it.
    """

    def test_no_base_package_imports_a_feature(self) -> None:
        offenders: list[str] = []

        for package in BASE_PACKAGES:
            root = APP / package
            if not root.exists():
                continue
            for file in _python_files(root):
                bad = {m for m in _imports(file) if m.startswith("app.features")}
                if bad:
                    offenders.append(f"{_rel(file)} imports {', '.join(sorted(bad))}")

        assert not offenders, (
            "The base imports a feature. Move what it needs into the base, or invert "
            "the call so the feature reaches down:\n  " + "\n  ".join(offenders)
        )

    def test_only_composition_roots_name_features(self) -> None:
        """
        Outside the base packages there is still application wiring — routers, the
        Celery app — and those legitimately name every feature. Everything else that
        does is a coupling nobody decided on.
        """
        offenders: list[str] = []

        for file in _python_files(APP):
            rel = _rel(file)
            if rel.startswith("features/") or rel in WIRING_POINTS:
                continue
            bad = {m for m in _imports(file) if m.startswith("app.features")}
            if bad:
                offenders.append(f"{rel} imports {', '.join(sorted(bad))}")

        assert not offenders, (
            "A feature is named outside a composition root. Add the file to "
            "WIRING_POINTS only if assembling the app is genuinely its job:\n  "
            + "\n  ".join(offenders)
        )


class TestFeaturesDoNotKnowAboutEachOther:
    """
    Direction 2. Two features sharing code through each other rather than through the
    base is the point at which "separate modules" stops being true — deleting one
    would break the other, which is the definition of not being separate.
    """

    def test_no_feature_imports_another(self) -> None:
        features_root = APP / "features"
        if not features_root.exists():
            pytest.skip("no features package yet")

        offenders: list[str] = []
        for file in _python_files(features_root):
            mine = _feature_of(file)
            if mine is None:
                continue
            for module in _imports(file):
                if not module.startswith("app.features."):
                    continue
                theirs = module.split(".")[2] if len(module.split(".")) > 2 else None
                if theirs and theirs != mine:
                    offenders.append(f"{_rel(file)} imports {module}")

        assert not offenders, (
            "One feature imports another. Whatever they share belongs in the base:\n  "
            + "\n  ".join(offenders)
        )


class TestTheRuleIsBeingApplied:
    """A test that passes because nothing is arranged yet is not a guard."""

    def test_there_are_features_to_check(self) -> None:
        features = {
            p.name
            for p in (APP / "features").iterdir()
            if p.is_dir() and p.name != "__pycache__"
        }

        assert features, "expected feature packages under app/features/"

    def test_the_import_reader_actually_reads_imports(self) -> None:
        """The whole guard rests on this. If it silently returned nothing — a parse
        error swallowed, say — every assertion above would pass on any codebase."""
        found = _imports(APP / "features" / "ask" / "service.py")

        assert "app.knowledge.questions" in found, (
            f"expected the ask service to import from the knowledge base; got {sorted(found)[:8]}"
        )
