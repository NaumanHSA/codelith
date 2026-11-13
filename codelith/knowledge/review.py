"""
Review: a change, checked against what the knowledge base knows.

Before a change is merged — written by a person or by an agent — this says what it
touches and whether it fits how the code is put together:

- which files and parts it changes, and which functions in them
- what else could break: everything that reaches each file within three hops, which
  tests do, and which written pages describe it (`knowledge/preflight.py`, per file)
- what it adds or removes that the outside world sees: routes, commands, settings,
  outside services — read from the changed files with the same detectors analysis uses
- whether it breaks the codebase's shape (`knowledge/shape.py`): an import running
  backwards against the columns, a dependency between two parts that had none, a new
  loop between parts, a deleted or renamed file something still imports

Base, not an app, for the same reason as the pre-flight: MCP serves it, and it derives
nothing of its own beyond parsing the changed files with the language providers.

The knowledge base describes the code at its commit. A change is read against that:
the old line numbers are the reading's, the new contents come from the change. When
the change was taken against another base, the report says the old side is approximate.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.knowledge.atlas import Atlas, AtlasService
from codelith.knowledge.builder import SourceFile, build_modules
from codelith.knowledge.changes import ChangedFile, ChangeSet, overlaps
from codelith.knowledge.constants import EntityKind
from codelith.knowledge.preflight import Preflight, PreflightService
from codelith.knowledge.shape import TIERS, Shape, shape_of
from codelith.languages.registry import registry
from codelith.models.graph import GraphSymbol
from codelith.models.knowledge import KBEntity, KnowledgeBase

logger = structlog.get_logger(__name__)

STOP, WARN, NOTE = "stop", "warn", "note"
_ORDER = {STOP: 0, WARN: 1, NOTE: 2}
_RISK = {"unknown": -1, "low": 0, "moderate": 1, "high": 2}

#: Facts whose removal can break something outside the codebase: a client calling a
#: route, a script running a command, a scheduler, a subscriber.
_BREAKING_IF_REMOVED = {
    EntityKind.ROUTE,
    EntityKind.CLI_COMMAND,
    EntityKind.SCHEDULED_TASK,
    EntityKind.EVENT,
    EntityKind.ENTRYPOINT,
}
#: Facts worth mentioning when they appear or go; the rest (dependencies, test suites)
#: are visible enough in the diff itself.
_WORTH_SAYING = _BREAKING_IF_REMOVED | {
    EntityKind.ENV_VAR,
    EntityKind.EXTERNAL_API,
    EntityKind.DATASTORE,
    EntityKind.SERVICE,
    EntityKind.INFRA_RESOURCE,
}

_SYMBOLS_SHOWN = 8


@dataclass(slots=True)
class Finding:
    kind: str
    severity: str
    message: str
    path: str | None = None
    line: int | None = None


@dataclass(slots=True)
class FileImpact:
    path: str
    status: str
    old_path: str | None
    part: str | None
    symbols: list[str] = field(default_factory=list)
    dependents: int = 0
    reach: int = 0
    tests: list[str] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)
    risk: str = "unknown"
    imports_added: list[str] = field(default_factory=list)
    imports_removed: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PartLink:
    """A link between two parts that this change creates."""

    source: int
    target: int
    file: str
    imports: str
    line: int | None
    #: `new` | `backwards` | `loop` | `existing`
    kind: str


@dataclass(slots=True)
class Review:
    commit: str | None
    base: str
    head: str | None
    files: list[FileImpact] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    links: list[PartLink] = field(default_factory=list)
    #: The parts the change touches or links to: index, name, column.
    parts: list[dict] = field(default_factory=list)
    facts_added: list[str] = field(default_factory=list)
    facts_removed: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)
    risk: str = "low"
    verdict: str = "clear"
    summary: str = ""
    skipped: int = 0
    #: Open QA findings in the changed files, and the ids of those it removes or fixes.
    qa_open: int = 0
    qa_fixed: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def brief(self) -> str:
        """The report as prose an agent or a terminal reads top to bottom. Empty sections
        are left out: a report padded with zeros teaches its reader to skim."""
        out = [self.summary, ""]
        for severity, title in ((STOP, "Stop and look"), (WARN, "Check"), (NOTE, "Notes")):
            rows = [f for f in self.findings if f.severity == severity]
            if rows:
                out.append(f"{title}:")
                for f in rows:
                    where = f"{f.path}:{f.line}" if f.path and f.line else (f.path or "")
                    out.append(f"  {where + '  ' if where else ''}{f.message}")
                out.append("")
        if self.files:
            out.append("What it touches:")
            for f in self.files:
                mark = {"added": "A", "deleted": "D", "renamed": "R"}.get(f.status, "M")
                bits = [b for b in (f.part, f"{f.risk} risk" if f.risk != "unknown" else None) if b]
                if f.reach:
                    bits.append(f"{f.reach} file(s) reach it")
                out.append(f"  {mark} {f.path}" + (f"  ({', '.join(bits)})" if bits else ""))
                if f.symbols:
                    out.append(f"      changes {', '.join(f.symbols)}")
            out.append("")
        if self.tests:
            out += ["Tests to run:", *(f"  {t}" for t in self.tests), ""]
        if self.pages:
            out += ["Written pages to check:", *(f"  {p['address']} — {p['title']}" for p in self.pages), ""]
        if self.skipped:
            out += [f"{self.skipped} more file(s) were left out: the change is larger than a review reads.", ""]
        return "\n".join(out).rstrip() + "\n"


class ReviewService:
    """Reviews one change against one knowledge base."""

    def __init__(self, db: AsyncSession, kb: KnowledgeBase) -> None:
        self.db = db
        self.kb = kb

    async def review(self, change: ChangeSet) -> Review:
        kb = self.kb
        atlas = await AtlasService(self.db, kb).build()
        shape = shape_of(atlas)
        report = Review(commit=kb.commit_sha, base=change.base, head=change.head, skipped=change.skipped)

        files_ix = {n.path: i for i, n in enumerate(atlas.nodes) if not n.fact}
        renamed = {f.old_path: f.path for f in change.files if f.status == "renamed" and f.old_path}
        gone = {f.before for f in change.files if f.status in ("deleted", "renamed")}
        known = (set(files_ix) - gone) | {f.path for f in change.files if f.status != "deleted"}

        old_imports: dict[str, set[str]] = {}
        for a, b in atlas.edges:
            na, nb = atlas.nodes[a], atlas.nodes[b]
            if not na.fact and not nb.fact:
                old_imports.setdefault(na.path, set()).add(nb.path)

        symbols = await self._symbols({f.before for f in change.files})
        old_facts = await self._facts({f.before for f in change.files})

        new_imports: dict[str, dict[str, int | None]] = {}
        facts_now: set[tuple[str, str]] = set()
        facts_before: set[tuple[str, str]] = set()
        reports: dict[str, Preflight] = {}
        preflight = PreflightService(self.db, kb.id, kb.project_id)

        for f in change.files:
            provider = registry.for_path(f.path)
            pre = None
            if f.status != "added" and f.before in files_ix:
                pre = await preflight.inspect(f.before)
                reports[f.path] = pre

            impact = FileImpact(
                path=f.path,
                status=f.status,
                old_path=f.old_path,
                part=self._part_name(atlas, self._component(atlas, files_ix, f.before if f.before in files_ix else f.path)),
            )
            if pre is not None and pre.found:
                impact.dependents = len(pre.dependents)
                impact.reach = len(pre.reached)
                impact.tests = list(pre.tests)
                impact.pages = [{"address": p.address, "title": p.title} for p in pre.documented_in]
                impact.risk = pre.risk
            impact.symbols = self._touched(f, symbols.get(f.before, []), provider)

            # What it imports now, resolved against the files that exist after the change.
            if f.content is not None and provider is not None:
                found: dict[str, int | None] = {}
                every = frozenset(known)
                for ref in provider.extract_imports(f.content, f.path):
                    # Resolved as the reading resolved them, or an import style the
                    # graph understands would seem added or removed here.
                    for target in provider.resolve_import_all(ref, f.path, every):
                        if target != f.path:
                            found.setdefault(target, ref.line)
                new_imports[f.path] = found
                before = {renamed.get(t, t) for t in old_imports.get(f.before, set())}
                impact.imports_added = sorted(set(found) - before)
                impact.imports_removed = sorted(before - set(found))

            # Facts it declares now, against those the reading recorded for it — only where
            # the new contents could be read, or a binary file would seem to remove them all.
            if f.status == "deleted" or f.content is not None:
                facts_before |= {(k, n) for k, n, _ in old_facts.get(f.before, [])}
            if f.content is not None:
                built = build_modules([SourceFile(path=f.path, content=f.content, language=None)])
                facts_now |= {(e["kind"], e["name"]) for e in built.entities}

            report.files.append(impact)

        self._shape(report, atlas, shape, files_ix, change, new_imports)
        self._broken_imports(report, change, reports)
        self._facts_moved(report, facts_now, facts_before)
        self._coverage(report, change, reports)
        await self._qa(report, change)
        self._verdict(report, atlas, shape)
        return report

    async def _qa(self, report: Review, change: ChangeSet) -> None:
        """
        Open QA findings in the changed files: the ones a change removes with its file,
        the ones a language rule no longer finds in the new contents (fixed), and the
        rest whose lines it touches. The first two are said as fact; "touches" only
        says to look, since only the next QA run can tell.
        """
        from codelith.knowledge.findings import FindingsReader, touching

        try:
            known = await FindingsReader(self.db, self.kb.project_id).open()
        except Exception as exc:  # pragma: no cover - defensive: a review never fails over QA
            logger.warning("review_findings_failed", error=str(exc))
            return
        report.qa_open = sum(1 for k in known if k.path in {f.before for f in change.files})
        for f in change.files:
            here = touching(known, f.before)
            if not here:
                continue
            if f.status == "deleted":
                for k in here:
                    report.qa_fixed.append(k.id)
                    report.findings.append(Finding("qa-gone", NOTE, f"Removes the file of QA finding #{k.id}: {k.title}", f.path, k.line))
                continue
            still: set[tuple[str, str]] | None = None
            provider = registry.for_path(f.path)
            if f.content is not None and provider is not None and provider.has_rules:
                still = {
                    (i.rule, _flat(f.content.splitlines()[i.line - 1] if 0 < i.line <= len(f.content.splitlines()) else ""))
                    for i in provider.inspect(f.path, f.content)
                }
            touched = {k.id for k in touching(here, f.before, f.old_ranges)}
            for k in here:
                first = _flat((k.snippet or "").splitlines()[0] if k.snippet else "")
                if k.source == "rule" and still is not None and first and (k.rule, first) not in still:
                    report.qa_fixed.append(k.id)
                    report.findings.append(
                        Finding("qa-fixed", NOTE, f"Fixes QA finding #{k.id}: {k.title} — the rule no longer finds it.", f.path, k.line)
                    )
                elif k.id in touched:
                    report.findings.append(
                        Finding(
                            "qa-touched",
                            WARN if k.severity in ("critical", "high") else NOTE,
                            f"Changes the lines of open QA finding #{k.id} ({k.severity}): {k.title}. "
                            "Check it is fixed, not moved; the next QA run will say.",
                            f.path,
                            k.line,
                        )
                    )

    # ── lookups ──────────────────────────────────────────────────────────────

    async def _symbols(self, paths: set[str]) -> dict[str, list[tuple[str, int | None, int | None]]]:
        if not paths:
            return {}
        rows = (
            await self.db.execute(
                select(GraphSymbol.path, GraphSymbol.qname, GraphSymbol.line, GraphSymbol.end_line).where(
                    GraphSymbol.project_id == self.kb.project_id,
                    GraphSymbol.kb_id == self.kb.id,
                    GraphSymbol.path.in_(paths),
                )
            )
        ).all()
        out: dict[str, list[tuple[str, int | None, int | None]]] = {}
        for path, qname, line, end in rows:
            out.setdefault(path, []).append((qname, line, end))
        return out

    async def _facts(self, paths: set[str]) -> dict[str, list[tuple[str, str, int | None]]]:
        if not paths:
            return {}
        rows = (
            await self.db.execute(
                select(KBEntity.source_path, KBEntity.kind, KBEntity.name, KBEntity.source_line).where(
                    KBEntity.kb_id == self.kb.id, KBEntity.source_path.in_(paths)
                )
            )
        ).all()
        out: dict[str, list[tuple[str, str, int | None]]] = {}
        for path, kind, name, line in rows:
            out.setdefault(path, []).append((kind, name, line))
        return out

    @staticmethod
    def _component(atlas: Atlas, files_ix: dict[str, int], path: str) -> int | None:
        """A file's part. A new file joins the part most of its neighbours are in."""
        if path in files_ix:
            return atlas.nodes[files_ix[path]].component
        folder = PurePosixPath(path).parent
        while True:
            near = Counter(
                atlas.nodes[i].component for p, i in files_ix.items() if PurePosixPath(p).parent == folder
            )
            if near:
                return near.most_common(1)[0][0]
            if folder == folder.parent or str(folder) in ("", "."):
                return None
            folder = folder.parent

    @staticmethod
    def _part_name(atlas: Atlas, component: int | None) -> str | None:
        return atlas.components[component].name if component is not None else None

    @staticmethod
    def _touched(f: ChangedFile, old: list[tuple[str, int | None, int | None]], provider) -> list[str]:
        """The functions and classes the change edits: the reading's symbols on the old
        side of the diff, and the file's own symbols now on the new side."""
        names: list[str] = []
        if f.status not in ("added",):
            names += [q for q, line, end in old if overlaps(f.old_ranges, line, end)]
        if f.content is not None and provider is not None:
            try:
                for s in provider.extract_symbols(f.content, f.path):
                    if f.status == "added" or overlaps(f.new_ranges, s.line, s.end_line):
                        names.append(s.qualified_name)
            except Exception:  # a provider that chokes on half-written code is not fatal
                logger.debug("review_symbols_failed", path=f.path, exc_info=True)
        # The innermost first matters less than not repeating `Class` and `Class.method`.
        seen: list[str] = []
        for n in names:
            if n not in seen:
                seen.append(n)
        if len(seen) > _SYMBOLS_SHOWN:
            return [*seen[:_SYMBOLS_SHOWN], f"+{len(seen) - _SYMBOLS_SHOWN} more"]
        return seen

    # ── the checks ───────────────────────────────────────────────────────────

    def _shape(
        self,
        report: Review,
        atlas: Atlas,
        shape: Shape,
        files_ix: dict[str, int],
        change: ChangeSet,
        new_imports: dict[str, dict[str, int | None]],
    ) -> None:
        """New links between parts, held against the columns and the existing links."""
        tests = {f.path for f in change.files if _is_test(f.path)}
        created: set[tuple[int, int]] = set()
        # More of a backwards link the codebase already had: said once per pair of parts,
        # not once per import, or a large change buries what is new under what is not.
        more_of: dict[tuple[int, int], list[tuple[str, int | None]]] = {}
        for impact in report.files:
            if impact.path in tests or not impact.imports_added:
                continue
            ca = self._component(atlas, files_ix, impact.path)
            for target in impact.imports_added:
                cb = self._component(atlas, files_ix, target)
                if ca is None or cb is None or ca == cb:
                    continue
                line = new_imports.get(impact.path, {}).get(target)
                existed = (ca, cb) in shape.links
                ta, tb = shape.tiers[ca], shape.tiers[cb]
                backwards = ta >= 0 and tb >= 0 and ta > tb
                loop = not existed and shape.reaches(cb, ca, created)
                kind = "existing" if existed else "loop" if loop else "backwards" if backwards else "new"
                if (ca, cb) not in {(link.source, link.target) for link in report.links}:
                    report.links.append(PartLink(ca, cb, impact.path, target, line, kind))
                created.add((ca, cb))
                a, b = atlas.components[ca].name, atlas.components[cb].name
                if existed:
                    if backwards:
                        more_of.setdefault((ca, cb), []).append((impact.path, line))
                    continue
                if loop:
                    report.findings.append(
                        Finding(
                            "loop",
                            STOP,
                            f"Imports {target}, so {a} now depends on {b} — and {b} already depends on {a}. "
                            "That makes a loop between the two parts.",
                            impact.path,
                            line,
                        )
                    )
                elif backwards:
                    report.findings.append(
                        Finding(
                            "layering",
                            STOP,
                            f"Imports {target}, so {a} ({TIERS[ta][0].lower()}) now depends on {b} "
                            f"({TIERS[tb][0].lower()}). That runs against the way this codebase is put together.",
                            impact.path,
                            line,
                        )
                    )
                else:
                    report.findings.append(
                        Finding(
                            "new_dependency",
                            WARN,
                            f"Imports {target}, so {a} now depends on {b}, which it did not before.",
                            impact.path,
                            line,
                        )
                    )

        for (ca, cb), where in more_of.items():
            a, b = atlas.components[ca].name, atlas.components[cb].name
            first, line = where[0]
            report.findings.append(
                Finding(
                    "layering",
                    NOTE,
                    f"{len(where)} new import(s) add to {a} depending on {b} against the columns — "
                    "a link the codebase already had, made a little stronger.",
                    first,
                    line,
                )
            )

    @staticmethod
    def _broken_imports(
        report: Review,
        change: ChangeSet,
        reports: dict[str, Preflight],
    ) -> None:
        """A deleted or renamed file that something not in this change still imports."""
        changed = {f.path for f in change.files} | {f.before for f in change.files} | set(change.left_out)
        for f in change.files:
            if f.status not in ("deleted", "renamed"):
                continue
            pre = reports.get(f.path)
            if pre is None:
                continue
            # Files outside the change that import it are certainly broken. One inside the
            # change may have been fixed — or not; its old import no longer resolves to a
            # path, so it cannot be told apart, and the diff is the place to look.
            still = sorted(d for d in pre.dependents if d not in changed)
            if not still:
                continue
            names = ", ".join(still[:4]) + (f" and {len(still) - 4} more" if len(still) > 4 else "")
            message = (
                f"Deletes {f.before}, which {len(still)} file(s) not in this change still import: {names}."
                if f.status == "deleted"
                else f"Renames {f.before} to {f.path}, but {len(still)} file(s) not in this change "
                f"still import the old path: {names}."
            )
            report.findings.append(Finding("broken_import", STOP, message, f.before, None))

    @staticmethod
    def _facts_moved(report: Review, now: set[tuple[str, str]], before: set[tuple[str, str]]) -> None:
        added = sorted((k, n) for k, n in now - before if k in _WORTH_SAYING)
        removed = sorted((k, n) for k, n in before - now if k in _WORTH_SAYING)
        report.facts_added = [f"{_fact_label(k)} {n}" for k, n in added]
        report.facts_removed = [f"{_fact_label(k)} {n}" for k, n in removed]
        for k, n in removed:
            if k in _BREAKING_IF_REMOVED:
                report.findings.append(
                    Finding(
                        "removed_" + str(k),
                        WARN,
                        f"Removes the {_fact_label(k)} {n}. Anything outside the codebase that uses it will break.",
                    )
                )
        if added:
            report.findings.append(
                Finding("added_facts", NOTE, "Adds " + "; ".join(f"{_fact_label(k)} {n}" for k, n in added[:6]) + ".")
            )
        quiet_removed = [(k, n) for k, n in removed if k not in _BREAKING_IF_REMOVED]
        if quiet_removed:
            report.findings.append(
                Finding(
                    "removed_facts",
                    NOTE,
                    "No longer uses " + "; ".join(f"{_fact_label(k)} {n}" for k, n in quiet_removed[:6]) + ".",
                )
            )

    @staticmethod
    def _coverage(report: Review, change: ChangeSet, reports: dict[str, Preflight]) -> None:
        tests: set[str] = {f.path for f in change.files if f.status != "deleted" and _is_test(f.path)}
        pages: dict[str, dict] = {}
        for impact in report.files:
            tests.update(impact.tests)
            for p in impact.pages:
                pages[p["address"]] = p
            pre = reports.get(impact.path)
            if (
                pre is not None
                and impact.status == "modified"
                and not _is_test(impact.path)
                and pre.risk == "high"
                and not pre.tests
            ):
                report.findings.append(
                    Finding(
                        "untested",
                        WARN,
                        f"No test reaches it, and {len(pre.reached)} file(s) depend on it. "
                        "A mistake here would not be caught by the suite.",
                        impact.path,
                    )
                )
        report.tests = sorted(tests)
        report.pages = sorted(pages.values(), key=lambda p: p["address"])
        if report.pages:
            report.findings.append(
                Finding(
                    "pages",
                    NOTE,
                    f"{len(report.pages)} written page(s) describe code this changes; check them once it lands.",
                )
            )

    @staticmethod
    def _verdict(report: Review, atlas: Atlas, shape: Shape) -> None:
        report.findings.sort(key=lambda f: (_ORDER[f.severity], f.path or "", f.line or 0))
        stops = sum(1 for f in report.findings if f.severity == STOP)
        warns = sum(1 for f in report.findings if f.severity == WARN)
        report.verdict = "stop" if stops else "check" if warns else "clear"
        risks = [f.risk for f in report.files if f.risk in _RISK]
        report.risk = max(risks, key=lambda r: _RISK[r], default="low")
        if report.risk == "unknown":
            report.risk = "low"

        touched = {c for c in (_index(atlas, f.part) for f in report.files) if c is not None}
        linked = {c for link in report.links for c in (link.source, link.target)}
        report.parts = [
            {"index": c, "name": atlas.components[c].name, "tier": shape.tiers[c], "touched": c in touched}
            for c in sorted(touched | linked)
        ]

        n = len(report.files)
        if not n:
            report.summary = f"Nothing changed against {_short(report.base)}."
            return
        across = f" across {len(touched)} part{'s' if len(touched) != 1 else ''}" if touched else ""
        head = f"{n} changed file{'s' if n != 1 else ''}{across}, {report.risk} risk"
        if report.verdict == "stop":
            tail = f"{stops} thing{'s' if stops != 1 else ''} to stop and look at before merging"
        elif report.verdict == "check":
            tail = f"{warns} thing{'s' if warns != 1 else ''} worth checking"
        else:
            tail = "nothing that breaks the codebase's shape"
        against = f" against {_short(report.base)}"
        if report.commit and report.base and not report.commit.startswith(report.base) and not report.base.startswith(
            report.commit[:7]
        ):
            against += f" (the knowledge is from {_short(report.commit)}; old line numbers are approximate)"
        report.summary = f"{head}{against}: {tail}."


def _index(atlas: Atlas, name: str | None) -> int | None:
    if name is None:
        return None
    for i, c in enumerate(atlas.components):
        if c.name == name:
            return i
    return None


def _short(ref: str | None) -> str:
    if not ref:
        return "the working copy"
    return ref[:8] if len(ref) >= 32 else ref


def _fact_label(kind: str) -> str:
    return {
        "route": "route",
        "cli_command": "command",
        "scheduled_task": "scheduled task",
        "event": "event",
        "entrypoint": "entry point",
        "env_var": "setting",
        "external_api": "outside service",
        "datastore": "datastore",
        "service": "service",
        "infra_resource": "infrastructure",
    }.get(str(kind), str(kind).replace("_", " "))


def _flat(text: str) -> str:
    return "".join(text.split())


def _is_test(path: str) -> bool:
    provider = registry.for_path(path)
    return bool(provider and provider.is_test_file(path))


__all__ = ["Finding", "FileImpact", "PartLink", "Review", "ReviewService"]
