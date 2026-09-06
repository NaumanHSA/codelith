"""
What an edit touches, answered before the edit is made.

A coding agent about to change a function knows what the function does — it has the
file open. What it does not know, and cannot cheaply find out, is what depends on that
function, whether anything tests it, and what has already been written about it. Every
agent rediscovers this by grepping, badly, once per session, and the usual failure is
not a wrong edit but a *confidently narrow* one: the change is correct in the file and
breaks four callers the agent never looked for.

Codelith has already read the repository — imports, call edges, symbol positions, the
provenance of every written page — and pinned the result to a commit. This assembles
that into the one answer worth having up front:

    codelith/llm/client.py — high risk to edit.
    3 files import it directly, 11 reach it within 3 hops, and nothing tests it.

**No model call and no re-reading.** Four indexed queries against the knowledge base.
The whole point is that it is cheap enough to run before every edit, because a check
an agent skips under time pressure is a check that does not exist.

**Degrades, never fails.** A path missing from the graph loses one section, not the
answer — the same rule the parked Quality app followed, for the same reason: a
pre-flight that returns nothing because one lookup was unlucky is worse than one that
returns four sections out of five.

`reach_weight` is the ranking, lifted here deliberately. It was Quality's, scoring
findings by what they touch rather than by severity alone; it is not specific to
findings, and leaving it inside one app meant every other caller re-invented a worse
version. It lives in the base now so ranking by reach is available to whatever asks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.languages import registry
from codelith.memory import get_graph_store
from codelith.models.knowledge import KBEntity
from codelith.models.site import DocPage, DocSite

logger = structlog.get_logger(__name__)

#: Reach beyond which extra dependents stop changing the decision. A file two hundred
#: modules import is not twice as dangerous as one a hundred import — both mean "this
#: is load-bearing", and without a ceiling the single most-imported file in a
#: repository crowds out everything else in any ranking built on this.
REACH_CEILING = 40

#: How far up the import graph to walk. Three hops is what a person reads; past that
#: the answer is "most of the repository" and the list stops being actionable.
_DEPTH = 3

#: Rows shown per section. Enough to check the claim, few enough to read.
_SAMPLE = 12


def reach_weight(reached_files: int, documented_pages: int = 0) -> int:
    """
    How much a file's surroundings should count when ranking work against it.

    Reach is capped (see `REACH_CEILING`); written pages are worth five files each,
    because a page describing code is a claim somebody published, and breaking it
    costs more than breaking an import nobody reads.
    """
    return min(max(reached_files, 0), REACH_CEILING) + max(documented_pages, 0) * 5


@dataclass(frozen=True, slots=True)
class Caller:
    """Something that calls into the target."""

    file: str
    symbol: str


@dataclass(frozen=True, slots=True)
class Reached:
    """A file that imports the target, directly or through others."""

    path: str
    distance: int
    is_test: bool


@dataclass(frozen=True, slots=True)
class CitedBy:
    """A written page whose provenance names the target."""

    address: str
    title: str


@dataclass(slots=True)
class Preflight:
    """Everything known about what an edit here would touch."""

    #: What the caller asked about, verbatim.
    target: str
    #: What that resolved to. Empty when nothing matched.
    files: list[str] = field(default_factory=list)
    #: `file`, `symbol`, or `unknown` — how the target was understood.
    kind: str = "unknown"
    #: Where a symbol target is defined, as `path:line`. Empty for file targets.
    defined_at: list[str] = field(default_factory=list)

    callers: list[Caller] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)
    #: What the target imports. The other three legs of the graph have always been
    #: here; this one existed on the store and was reachable only through MCP, so
    #: "what does this depend on" was the one question the pre-flight could not
    #: answer about the file it was describing.
    imports: list[str] = field(default_factory=list)
    reached: list[Reached] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    documented_in: list[CitedBy] = field(default_factory=list)
    #: Facts the analysis extracted from these files — routes, env vars, entrypoints.
    facts: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.files)

    @property
    def weight(self) -> int:
        return reach_weight(len(self.reached), len(self.documented_in))

    @property
    def risk(self) -> str:
        """
        `low` | `moderate` | `high` | `unknown`.

        Untested is an amplifier rather than a level of its own: a leaf nothing
        imports is safe to change whether or not a test covers it, and a file eleven
        others reach with no test is the case worth stopping for.
        """
        if not self.found:
            return "unknown"
        weight = self.weight
        if weight == 0:
            return "low"
        if weight >= 25 or (weight >= 8 and not self.tests):
            return "high"
        if weight >= 8 or not self.tests:
            return "moderate"
        return "low"

    def headline(self) -> str:
        """One sentence, for a reader who will act on nothing else."""
        if not self.found:
            return f"Nothing in this codebase resolves to '{self.target}'."

        bits = []
        if self.dependents:
            bits.append(f"{len(self.dependents)} file(s) import it directly")
        if len(self.reached) > len(self.dependents):
            bits.append(f"{len(self.reached)} reach it within {_DEPTH} hops")
        if self.callers:
            bits.append(f"{len(self.callers)} call site(s)")
        bits.append(
            f"{len(self.tests)} test file(s) reach it" if self.tests else "nothing tests it"
        )
        if self.documented_in:
            bits.append(f"{len(self.documented_in)} written page(s) describe it")
        return f"{self.risk} risk to edit — " + ", ".join(bits) + "."

    def brief(self) -> str:
        """
        The whole answer, as prose an agent reads top to bottom.

        Sections that would be empty are omitted rather than printed as zero. A
        pre-flight padded with "0 callers" teaches its reader to skim, and the one
        line that mattered is in the part they skimmed.
        """
        if not self.found:
            return (
                f"Nothing in this codebase resolves to '{self.target}'. It may be a "
                "new file, may be excluded from analysis, or the analysis may predate "
                "it — re-analyse if the code has moved since."
            )

        out = [f"{', '.join(self.files[:3])} — {self.headline()}", ""]

        if self.defined_at:
            out += ["Defined at:", *(f"  {d}" for d in self.defined_at[:_SAMPLE]), ""]
        if self.callers:
            out += [
                "Called from:",
                *(f"  {c.file} :: {c.symbol}" for c in self.callers[:_SAMPLE]),
                "",
            ]
        if self.reached:
            out += [
                "Breaks first (nearest first):",
                *(
                    f"  {r.distance} hop(s)  {r.path}" + ("  [test]" if r.is_test else "")
                    for r in self.reached[:_SAMPLE]
                ),
                "",
            ]
        if self.tests:
            out += ["Covered by:", *(f"  {t}" for t in self.tests[:_SAMPLE]), ""]
        else:
            out += [
                "No test file reaches this. A change here is unverified by the suite.",
                "",
            ]
        if self.documented_in:
            out += [
                "Written pages that describe it (they will need re-writing):",
                *(f"  {p.address} — {p.title}" for p in self.documented_in[:_SAMPLE]),
                "",
            ]
        if self.imports:
            out += [
                "Depends on:",
                *(f"  {i}" for i in self.imports[:_SAMPLE]),
                "",
            ]
        if self.facts:
            out += ["Declares:", *(f"  {f}" for f in self.facts[:_SAMPLE]), ""]

        return "\n".join(out).rstrip() + "\n"


class PreflightService:
    """Assembles a `Preflight` for one target in one knowledge base."""

    def __init__(self, db: AsyncSession, kb_id: int, project_id: int) -> None:
        self.db = db
        self.kb_id = kb_id
        self.project_id = project_id

    async def inspect(self, target: str) -> Preflight:
        target = (target or "").strip()
        report = Preflight(target=target)
        if not target:
            return report

        await self._resolve(report)
        if not report.found:
            return report

        await self._graph(report)
        await self._documentation(report)
        await self._facts(report)
        return report

    # ── resolution ────────────────────────────────────────────────────────────

    async def _resolve(self, report: Preflight) -> None:
        """
        Work out whether the caller named a file or a symbol.

        A file is tried first and a symbol second, rather than guessing from the
        string: `main` is a plausible file *and* a plausible function, and a wrong
        guess produces a confident answer about the wrong thing. Trying both and
        preferring the file is a decision; inspecting the string for a dot is not.
        """
        try:
            async with get_graph_store(self.db) as graph:
                path = await graph.find_file(self.project_id, report.target)
                if path:
                    report.files = [path]
                    report.kind = "file"
                    return

                symbols = await graph.find_symbol(self.project_id, report.target)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("preflight_resolve_failed", target=report.target, error=str(exc))
            return

        if not symbols:
            return
        report.kind = "symbol"
        report.files = sorted({s["file"] for s in symbols})
        report.defined_at = [
            f"{s['file']}:{s['line']} ({s['kind'] or 'symbol'} {s['qname']})"
            for s in symbols[:_SAMPLE]
        ]

    # ── the four lookups ──────────────────────────────────────────────────────

    async def _graph(self, report: Preflight) -> None:
        """Callers, importers, imports, transitive reach — and which of those are tests."""
        try:
            async with get_graph_store(self.db) as graph:
                if report.kind == "symbol":
                    rows = await graph.get_callers(self.project_id, report.target.split(".")[-1])
                    report.callers = [Caller(r["file"], r["caller"]) for r in rows]

                direct: set[str] = set()
                uses: set[str] = set()
                reached: dict[str, int] = {}
                for path in report.files:
                    direct.update(await graph.get_dependents(self.project_id, path))
                    uses.update(await graph.get_imports(self.project_id, path))
                    for row in await graph.get_blast_radius(self.project_id, path, depth=_DEPTH):
                        hit, distance = row["file"], row["distance"]
                        if hit not in reached or distance < reached[hit]:
                            reached[hit] = distance
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("preflight_graph_failed", target=report.target, error=str(exc))
            return

        # A file in the target set is not its own dependent — that is true and useless,
        # and for a symbol spanning two files it would report each as breaking the other.
        own = set(report.files)
        report.dependents = sorted(direct - own)
        # Same subtraction, same reason: a symbol spanning two files would otherwise
        # report each as importing the other.
        report.imports = sorted(uses - own)
        report.reached = [
            Reached(path, distance, _is_test(path))
            for path, distance in sorted(reached.items(), key=lambda kv: (kv[1], kv[0]))
            if path not in own
        ]
        report.tests = [r.path for r in report.reached if r.is_test]

    async def _documentation(self, report: Preflight) -> None:
        """
        Written pages whose provenance names one of these files.

        Only written ones. A planned page cites nothing yet, and telling an agent that
        a page it has not generated will need re-writing is a claim about the future.
        """
        rows = (
            await self.db.execute(
                select(DocPage.section_slug, DocPage.slug, DocPage.title, DocPage.source_files_json)
                .join(DocSite, DocSite.id == DocPage.site_id)
                .where(
                    DocSite.project_id == self.project_id,
                    DocPage.version_id.is_(None),  # the live site, not a frozen snapshot
                    DocPage.content_markdown.isnot(None),
                )
            )
        ).all()

        wanted = set(report.files)
        report.documented_in = [
            CitedBy(f"{section}/{slug}", title)
            for section, slug, title, sources in rows
            if wanted & set(sources or ())
        ]

    async def _facts(self, report: Preflight) -> None:
        """
        Routes, env vars, entrypoints declared in these files.

        The part an agent is most likely to break without noticing: renaming a handler
        is a local edit until you learn the file declares three HTTP routes.
        """
        rows = (
            await self.db.execute(
                select(KBEntity.kind, KBEntity.name, KBEntity.source_line).where(
                    KBEntity.kb_id == self.kb_id,
                    KBEntity.source_path.in_(report.files),
                )
            )
        ).all()
        report.facts = sorted(
            f"{kind} {name}" + (f" (line {line})" if line else "")
            for kind, name, line in rows
        )


def _is_test(path: str) -> bool:
    """
    Whether a path is a test file, asked of the language rather than of a regex.

    Every provider answers this its own way — Go by the `_test.go` suffix, TypeScript
    by `.spec.` or a `__tests__` directory — and the whole point of the language layer
    is that this module does not need to know which is which. An unrecognised
    extension is not a test.
    """
    provider = registry.for_path(path)
    return bool(provider and provider.is_test_file(path))


__all__ = [
    "Caller",
    "CitedBy",
    "Preflight",
    "PreflightService",
    "REACH_CEILING",
    "Reached",
    "reach_weight",
]
