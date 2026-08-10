"""
What the dependency manifests get wrong, without opening a socket.

**No network, deliberately.** "Nothing leaves your box" is the product's headline
claim, and asking PyPI what the current version of each package is would send the name
of every dependency a user has — which is a fingerprint of their codebase — to a third
party. Latest-version checking is a later, opt-in addition, not something to discover
mid-build.

That leaves four questions, all answerable from the manifest and the import graph
alone, and all of them things a person actually hits:

* **Imported but not declared.** Works on the developer's machine, fails on a clean
  install. The single most common broken-dependency bug there is.
* **Declared but never imported.** Install time and attack surface for nothing.
* **Unpinned.** Not wrong, but it means two installs a week apart can differ.
* **Conflicting.** The same package constrained two ways in two manifests — one of
  them is not what gets installed, and nobody knows which.

**The import-side checks are where the false positives live**, so both directions are
deliberately conservative: a name that cannot be mapped confidently is not reported.
A dependency audit that cries wolf is one nobody opens twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.knowledge.constants import EntityKind

logger = structlog.get_logger(__name__)


class DependencyIssue(StrEnum):
    UNDECLARED = "undeclared"
    UNUSED = "unused"
    UNPINNED = "unpinned"
    CONFLICTING = "conflicting"


#: Packages whose import name differs from what you install. Every one of these was a
#: false positive before it was here, and the list is the honest cost of not asking a
#: registry: it can only ever be partial, so a name that is not in it and does not
#: match its package is reported as *neither* undeclared nor unused.
IMPORT_ALIASES: dict[str, str] = {
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "jose": "python-jose",
    "jwt": "pyjwt",
    "dateutil": "python-dateutil",
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "psycopg2": "psycopg2-binary",
    "attr": "attrs",
    "slugify": "python-slugify",
    "multipart": "python-multipart",
    "google": "google-cloud",
    "OpenSSL": "pyopenssl",
    "Crypto": "pycryptodome",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "fitz": "pymupdf",
    "magic": "python-magic",
}

#: Tooling that is legitimately declared and never imported — it is invoked, not
#: called. Reporting `pytest` as unused in a repository full of tests is the fastest
#: way to teach somebody this list is noise.
NEVER_IMPORTED: frozenset[str] = frozenset({
    "pytest", "pytest-asyncio", "pytest-cov", "ruff", "mypy", "black", "flake8",
    "isort", "build", "twine", "hatchling", "setuptools", "wheel", "pip", "uv",
    "pre-commit", "tox", "coverage", "alembic", "uvicorn", "gunicorn", "celery",
    "types-requests", "types-pyyaml", "mkdocs", "mkdocs-material", "sphinx",
})

#: Whole families that are configured rather than imported. A mkdocs plugin is named
#: in `mkdocs.yml` and never appears in a `.py` file, so every one of them was
#: reported unused — eight of the nine on the first real run, which is exactly the
#: ratio that teaches a reader to close the tab.
PLUGIN_PREFIXES: tuple[str, ...] = (
    "mkdocs-", "pytest-", "sphinx-", "types-", "eslint-", "babel-plugin-",
    "flake8-", "ruff-", "pymdown-", "mkdocstrings",
)


@dataclass(slots=True)
class DependencyFinding:
    issue: DependencyIssue
    package: str
    detail: str = ""
    #: Where it was declared, or where it is imported from.
    where: str = ""


@dataclass(slots=True)
class DependencyReport:
    findings: list[DependencyFinding] = field(default_factory=list)
    declared_count: int = 0
    #: True when no manifest was found at all — then "nothing declared" is not a
    #: finding about the code, it is a finding about the analysis.
    no_manifest: bool = False

    @property
    def summary(self) -> str:
        if self.no_manifest:
            return "No dependency manifest was found in this codebase."
        if not self.findings:
            return f"All {self.declared_count} declared dependencies look consistent."
        return f"{len(self.findings)} of {self.declared_count} declared dependencies need a look."

    def by_issue(self) -> dict[str, list[DependencyFinding]]:
        grouped: dict[str, list[DependencyFinding]] = {}
        for finding in self.findings:
            grouped.setdefault(str(finding.issue), []).append(finding)
        return grouped


class DependencyAudit:
    def __init__(self, db: AsyncSession, kb_id: int, project_id: int) -> None:
        self.db = db
        self.kb_id = kb_id
        self.project_id = project_id
        self.repos = KnowledgeRepositories.for_session(db)

    async def run(self) -> DependencyReport:
        declared = await self.repos.entities.list_by_kind(
            self.kb_id, EntityKind.DEPENDENCY, limit=500
        )
        report = DependencyReport(declared_count=len(declared))
        if not declared:
            report.no_manifest = True
            return report

        report.findings.extend(_unpinned(declared))
        report.findings.extend(_conflicting(declared))

        imported = await self._imported_packages(self.project_id)
        if imported:
            names = {_canonical(d.name) for d in declared}
            report.findings.extend(_undeclared(imported, names))
            report.findings.extend(_unused(declared, imported))

        report.findings.sort(key=lambda f: (str(f.issue), f.package))
        logger.info(
            "qa_dependency_audit",
            kb_id=self.kb_id,
            declared=len(declared),
            findings=len(report.findings),
        )
        return report

    async def _imported_packages(self, project_id: int) -> set[str]:
        """
        Third-party packages the code actually imports.

        From the code graph's `Package` nodes, which the language providers created —
        they already separated a third-party import from a local one and from the
        standard library, and QA deciding that a second time would decide it
        differently.

        An unavailable graph returns nothing, and both import-side checks are then
        skipped rather than reported wrongly: with no import data, *every* dependency
        looks unused.
        """
        from codelith.memory.graph_store import GraphStore

        try:
            async with GraphStore() as graph:
                rows = await graph.query(
                    "MATCH (:File {project_id: $project_id})-[:DEPENDS_ON]->(p:Package) "
                    "RETURN DISTINCT p.name AS name",
                    project_id=project_id,
                )
        except Exception as exc:
            logger.warning("qa_graph_unavailable_for_deps", error=str(exc))
            return set()

        return {_canonical(r["name"]) for r in rows if r.get("name")}


def _canonical(name: str) -> str:
    """`Python-Slugify` and `python_slugify` are the same package to a registry."""
    return re.sub(r"[-_.]+", "-", (name or "").strip().lower())


def _unpinned(declared) -> list[DependencyFinding]:
    """No constraint at all — two installs a week apart can differ."""
    out = []
    for entity in declared:
        specifier = ((entity.data_json or {}).get("specifier") or "").strip()
        if not specifier:
            out.append(
                DependencyFinding(
                    issue=DependencyIssue.UNPINNED,
                    package=entity.name,
                    detail="No version constraint, so two installs can differ.",
                    where=entity.source_path or "",
                )
            )
    return out


def _conflicting(declared) -> list[DependencyFinding]:
    """The same package constrained two ways. One of them is not what gets installed."""
    seen: dict[str, list[tuple[str, str]]] = {}
    for entity in declared:
        specifier = ((entity.data_json or {}).get("specifier") or "").strip()
        seen.setdefault(_canonical(entity.name), []).append(
            (specifier, entity.source_path or "")
        )

    out = []
    for package, entries in seen.items():
        specifiers = {s for s, _ in entries if s}
        if len(specifiers) > 1:
            where = ", ".join(sorted({p for _, p in entries if p}))
            out.append(
                DependencyFinding(
                    issue=DependencyIssue.CONFLICTING,
                    package=package,
                    detail=f"Constrained as {' and '.join(sorted(specifiers))}.",
                    where=where,
                )
            )
    return out


def _undeclared(imported: set[str], declared: set[str]) -> list[DependencyFinding]:
    """
    Imported and not in any manifest — works here, fails on a clean install.

    An alias is resolved before comparing, and a name that is neither declared nor a
    known alias is still reported: the alias table only ever hides false positives,
    never real ones.
    """
    out = []
    for package in sorted(imported):
        resolved = _canonical(IMPORT_ALIASES.get(package, package))
        if resolved in declared or package in declared:
            continue
        # The other half of the namespace case: `opentelemetry` is imported and
        # `opentelemetry-sdk` is what gets installed. Declaring the distribution is
        # correct, so reporting the import as undeclared would be wrong.
        if any(d.startswith(f"{resolved}-") for d in declared):
            continue
        out.append(
            DependencyFinding(
                issue=DependencyIssue.UNDECLARED,
                package=package,
                detail="Imported by the code but declared in no manifest — a clean install would fail.",
            )
        )
    return out


def _unused(declared, imported: set[str]) -> list[DependencyFinding]:
    """
    Declared and never imported — install time and attack surface for nothing.

    Tooling is excluded: `pytest` and `ruff` are invoked, not imported, and reporting
    them is the fastest way to teach a reader that this list is noise. Whole plugin
    families go with them, since a mkdocs plugin is named in `mkdocs.yml` and never
    appears in a `.py` file at all.

    **This is the weakest of the four checks**, and the wording says so. It can only
    see imports the analysis recorded: a package used in a file that was skipped, or
    loaded by a string name, looks unused. So the detail reads "no import of it was
    found" rather than "it is unused" — the first is what was measured.
    """
    aliased = {_canonical(IMPORT_ALIASES.get(p, p)) for p in imported} | imported
    out = []
    for entity in declared:
        package = _canonical(entity.name)
        if package in aliased or package in NEVER_IMPORTED:
            continue
        if package.startswith(PLUGIN_PREFIXES):
            continue
        # A namespace package is imported by its first segment: `opentelemetry-sdk`
        # is declared, `opentelemetry` is imported.
        if package.split("-")[0] in aliased:
            continue
        out.append(
            DependencyFinding(
                issue=DependencyIssue.UNUSED,
                package=entity.name,
                detail="No import of it was found in the analysed code.",
                where=entity.source_path or "",
            )
        )
    return out


__all__ = [
    "DependencyAudit",
    "DependencyFinding",
    "DependencyIssue",
    "DependencyReport",
    "IMPORT_ALIASES",
    "NEVER_IMPORTED",
]
