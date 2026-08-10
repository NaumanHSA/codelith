"""
Which parts of the surface no test mentions.

Not line coverage. Line coverage says 84% and nobody can act on it — you cannot tell
from the number whether the untested 16% is error handling or a `__repr__`. This
counts things a reader recognises: *six of twenty-eight routes are named in no test*,
with the six listed.

**It is evidence, not proof, and says so.** A test that exercises `POST /v1/chat` via a
fixture never writes the string, and a test that mentions a route in a comment is not
testing it. Name matching finds the first kind of gap reliably and the second kind
never — so the number is a floor on what is untested, not a measurement of what is
tested, and the wording everywhere reflects that.

Presenting this as coverage would be the worst outcome: a number people trust that
does not mean what they think.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.knowledge.constants import EntityKind
from codelith.models.chunk import CodeChunk

logger = structlog.get_logger(__name__)

#: The surface worth asking about — things a reader would name in a conversation.
#: Not every entity kind: "this datastore has no test" is not a sentence anybody acts
#: on, and a dependency cannot be tested at all.
SURFACE_KINDS: tuple[str, ...] = (
    EntityKind.ROUTE,
    EntityKind.CLI_COMMAND,
    EntityKind.SCHEDULED_TASK,
    EntityKind.ENTRYPOINT,
)


@dataclass(slots=True)
class SurfaceItem:
    kind: str
    name: str
    where: str = ""
    #: Test files that name it. Empty means nothing found it — which is the finding.
    named_in: tuple[str, ...] = ()

    @property
    def covered(self) -> bool:
        return bool(self.named_in)


@dataclass(slots=True)
class CoverageReport:
    items: list[SurfaceItem] = field(default_factory=list)
    #: True when the analysis found no test files at all. Then every item is
    #: "uncovered" and the number means nothing — a repository with no tests needs to
    #: be told that, not handed a list of twenty-eight failures.
    no_tests_found: bool = False

    @property
    def uncovered(self) -> list[SurfaceItem]:
        return [i for i in self.items if not i.covered]

    @property
    def summary(self) -> str:
        if self.no_tests_found:
            return "No test files were found in this codebase, so nothing here is checked."
        if not self.items:
            return "No routes, commands or entry points were found to check."
        missing = len(self.uncovered)
        if not missing:
            return f"All {len(self.items)} routes, commands and entry points are named in a test."
        return (
            f"{missing} of {len(self.items)} routes, commands and entry points are "
            "named in no test."
        )

    def by_kind(self) -> dict[str, list[SurfaceItem]]:
        grouped: dict[str, list[SurfaceItem]] = {}
        for item in self.items:
            grouped.setdefault(item.kind, []).append(item)
        return grouped


class SurfaceCoverage:
    def __init__(self, db: AsyncSession, kb_id: int) -> None:
        self.db = db
        self.kb_id = kb_id
        self.repos = KnowledgeRepositories.for_session(db)

    async def measure(self) -> CoverageReport:
        report = CoverageReport()

        surface = await self._surface()
        if not surface:
            return report

        tests = await self._test_sources()
        if not tests:
            report.no_tests_found = True
            report.items = surface
            return report

        for item in surface:
            report.items.append(
                SurfaceItem(
                    kind=item.kind,
                    name=item.name,
                    where=item.where,
                    named_in=_named_in(item, tests),
                )
            )
        logger.info(
            "qa_coverage",
            kb_id=self.kb_id,
            surface=len(report.items),
            uncovered=len(report.uncovered),
        )
        return report

    async def _surface(self) -> list[SurfaceItem]:
        items: list[SurfaceItem] = []
        for kind in SURFACE_KINDS:
            rows = await self.repos.entities.list_by_kind(self.kb_id, kind, limit=200)
            for row in rows:
                items.append(
                    SurfaceItem(
                        kind=str(kind),
                        name=row.name,
                        where=(
                            f"{row.source_path}:{row.source_line}"
                            if row.source_path
                            else ""
                        ),
                    )
                )
        return items

    async def _test_sources(self) -> dict[str, str]:
        """
        `path -> content` for every chunk of every test file.

        Read from the knowledge base rather than the checkout: coverage is a property
        of what was analysed, and this way it answers without a clone. Chunks are a
        lossy reconstruction of a file, which does not matter here — a route named
        only in the gap between two chunks is a miss, and the number is already a
        floor rather than a measurement.
        """
        rows = (
            await self.db.execute(
                select(CodeChunk.source_path, CodeChunk.content).where(
                    CodeChunk.kb_id == self.kb_id
                )
            )
        ).all()

        sources: dict[str, list[str]] = {}
        for path, content in rows:
            if not _is_test(path or ""):
                continue
            sources.setdefault(path, []).append(content or "")
        return {path: "\n".join(parts) for path, parts in sources.items()}


def _is_test(path: str) -> bool:
    lowered = path.lower()
    parts = lowered.split("/")
    return (
        any(p in ("test", "tests", "testing", "spec", "specs", "__tests__") for p in parts)
        or parts[-1].startswith("test_")
        or parts[-1].endswith(("_test.py", "_test.go", ".test.ts", ".test.js", ".spec.ts"))
    )


def _named_in(item: SurfaceItem, tests: dict[str, str]) -> tuple[str, ...]:
    """
    Which test files mention this thing.

    A route is `GET /health`, and no test contains that string — it contains
    `"/health"`. So the path is what is searched for, and the method is dropped.
    Entry points are file paths, where the module name is what a test would import.
    """
    needles = _needles(item)
    if not needles:
        return ()

    found = [
        path
        for path, source in tests.items()
        if any(n in source for n in needles)
    ]
    return tuple(sorted(found))


def _needles(item: SurfaceItem) -> list[str]:
    """
    What to look for, per kind. Wrong needles are how this becomes a lie.

    A CLI command named after the package — `neurosurfer` — appears in every import
    line of every test, so a bare substring search reported it covered by
    `tests/fakes.py`, which tests nothing of the sort. A test that invokes a command
    passes its name as a *string*, so quoted forms are what count.
    """
    name = (item.name or "").strip()
    if item.kind == str(EntityKind.ROUTE):
        # "GET /v1/models" → "/v1/models". A test names the path, never the verb.
        path = name.split(" ", 1)[-1].strip()
        return [path] if len(path) > 1 else []

    if item.kind == str(EntityKind.ENTRYPOINT):
        # "neurosurfer/app/cli/app.py" → "neurosurfer.app.cli.app", how it is imported.
        module = re.sub(r"\.py$", "", name).replace("/", ".")
        stem = name.rsplit("/", 1)[-1]
        return [n for n in (module, stem) if len(n) > 3]

    if item.kind == str(EntityKind.CLI_COMMAND):
        # Quoted only. A command name is an argument in a test, not an identifier.
        return [f'"{name}"', f"'{name}'"] if len(name) > 1 else []

    return [name] if len(name) > 2 else []


__all__ = ["CoverageReport", "SURFACE_KINDS", "SurfaceCoverage", "SurfaceItem"]
