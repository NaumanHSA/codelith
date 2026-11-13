"""
A guided walk through a codebase for someone who has never seen it.

Start with what it is and how it is laid out, then where work comes in, one real
request followed from its handler to its data, the core, where the data lives, the
helpers everything leans on, and the files where an edit hurts most. Each stop names
the parts to open and the files to light on the knowledge graph, and — for the request
— the flow to play underneath.

No model is called. The words come from the narratives analysis already wrote (their
opening sentences) and from facts with a file behind them: counts, names, importers,
reach. A tour can be thin on a codebase analysis knew little about; it cannot describe
something that is not there.

An app by the registry rule: it reads the knowledge base and derives nothing analysis
should hold.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.knowledge.atlas import UNMAPPED, AtlasService
from codelith.knowledge.constants import EntityKind, NarrativeTopic
from codelith.knowledge.flows import Flow, FlowService
from codelith.knowledge.risk import RiskService
from codelith.knowledge.runbook import RunbookService
from codelith.knowledge.services import HOUSE_PARTS, SETUP
from codelith.knowledge.shape import TIERS, component_tiers
from codelith.models.knowledge import KBNarrative, KnowledgeBase
from codelith.models.project import Project

#: Tier positions in `shape.TIERS`.
_ENTRY, _CORE, _HELPERS, _DATA = 0, 1, 2, 3

#: Which way in a request is most worth following, best first.
_FLOW_PREFERENCE = ("route", "cli_command", "scheduled_task", "event", "entrypoint")


@dataclass(slots=True)
class TourFile:
    path: str
    #: Why it is at this stop, in a few words: "imported by 34 files".
    note: str = ""


@dataclass(slots=True)
class Stop:
    id: str
    title: str
    #: Markdown: two to four sentences, sometimes a short list.
    body: str
    #: Parts to open and frame, by name.
    parts: list[str] = field(default_factory=list)
    files: list[TourFile] = field(default_factory=list)
    #: A flow to play in the 2D panel, by id (`knowledge/flows.py`).
    flow: str | None = None


@dataclass(slots=True)
class Tour:
    project: str
    commit: str | None
    stops: list[Stop] = field(default_factory=list)

    def markdown(self) -> str:
        """The tour as a document, for a README or an onboarding page."""
        sha = (self.commit or "")[:8]
        out = [
            f"# A tour of {self.project}",
            "",
            f"_Written by Codelith from the reading at `{sha}`. Each stop names the files to open._"
            if sha
            else "_Written by Codelith from its reading. Each stop names the files to open._",
            "",
        ]
        for n, stop in enumerate(self.stops, 1):
            out += [f"## {n}. {stop.title}", "", stop.body.strip(), ""]
            if stop.files:
                out += [f"- `{f.path}`" + (f" — {f.note}" if f.note else "") for f in stop.files]
                out.append("")
        return "\n".join(out).rstrip() + "\n"


def _sentences(text: str | None, n: int, limit: int = 420) -> str:
    """The first `n` sentences of the first paragraph of prose: no headings, lists,
    tables or code. Cut at a sentence, never mid-word."""
    if not text:
        return ""
    for para in re.split(r"\n\s*\n", text):
        p = para.strip()
        if not p or p.startswith(("#", "|", "```", "- ", "* ", ">")):
            continue
        p = re.sub(r"\s+", " ", p)
        parts = [
            s
            for s in re.split(r"(?<=[.!?:])\s+(?=[A-Z`\"(])", p)
            if not s.endswith(":") and not _META.search(s)
        ]
        if not parts:
            # A paragraph that only introduces a list says nothing on its own.
            continue
        out = ""
        for s in parts[:n]:
            if out and len(out) + len(s) + 1 > limit:
                break
            out = f"{out} {s}".strip()
        return out
    return ""


#: Sentences about the material a narrative was written from rather than the code —
#: true where they were written, and no use to someone taking a tour.
_META = re.compile(r"\b(inventory|the evidence|the provided|excerpts?|not shown|is not visible)\b", re.I)


def _code(text: str) -> str:
    return f"`{text}`"


def _list(names: list[str], most: int = 4) -> str:
    """`a`, `b` and `c` — and N more."""
    shown = names[:most]
    if not shown:
        return ""
    head = ", ".join(shown[:-1]) + (" and " if len(shown) > 1 else "") + shown[-1]
    rest = len(names) - len(shown)
    return head + (f", and {rest} more" if rest > 0 else "")


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


class TourService:
    def __init__(self, db: AsyncSession, kb: KnowledgeBase) -> None:
        self.db = db
        self.kb = kb

    async def build(self) -> Tour:
        kb = self.kb
        atlas = await AtlasService(self.db, kb).build()
        project = await self.db.get(Project, kb.project_id)
        name = project.name if project else "this codebase"
        narratives = await self._narratives()
        flows = await FlowService(self.db, kb).flows()

        tiers = component_tiers(atlas)
        files = [i for i, n in enumerate(atlas.nodes) if not n.fact]
        members: Counter[int] = Counter(atlas.nodes[i].component for i in files)
        importers: Counter[int] = Counter()
        for a, b in atlas.edges:
            if not atlas.nodes[a].fact and not atlas.nodes[b].fact and a != b:
                importers[b] += 1

        def parts_in(tier: int) -> list[int]:
            return sorted(
                (
                    c
                    for c in range(len(atlas.components))
                    if tiers[c] == tier and members[c] and atlas.components[c].group not in HOUSE_PARTS
                ),
                key=lambda c: -members[c],
            )

        def most_imported(comps: list[int], k: int) -> list[TourFile]:
            ranked = sorted(
                (i for i in files if atlas.nodes[i].component in comps and importers[i]),
                key=lambda i: (-importers[i], atlas.nodes[i].path),
            )
            return [TourFile(atlas.nodes[i].path, f"imported by {_plural(importers[i], 'file')}") for i in ranked[:k]]

        tour = Tour(project=name, commit=kb.commit_sha)
        stops = tour.stops

        # 1. What it is.
        what = _sentences(narratives.get(NarrativeTopic.OVERVIEW), 3)
        size = (
            f"Codelith read {_plural(len(files), 'file')} at commit {_code((kb.commit_sha or '')[:8])} "
            f"and sorted them into {_plural(sum(1 for c in members if atlas.components[c].group not in HOUSE_PARTS), 'part')}."
        )
        stops.append(
            Stop(
                "start",
                f"What {name} is",
                (what + "\n\n" if what else "") + size + " This tour walks through them in the order a request meets them.",
            )
        )

        # 2. How it is laid out: the columns.
        columns = [(t, parts_in(t)) for t in range(len(TIERS))]
        lines = [
            f"- **{TIERS[t][0]}** — " + _list([atlas.components[c].name for c in cs], 5)
            for t, cs in columns
            if cs
        ]
        arch = _sentences(narratives.get(NarrativeTopic.ARCHITECTURE), 2)
        stops.append(
            Stop(
                "layout",
                "How it is laid out",
                (arch + "\n\n" if arch else "")
                + "The knowledge graph puts the parts in columns, in the order work moves through them:\n\n"
                + "\n".join(lines)
                + "\n\nImports run left to right. A part that imports one to its left is worth a second look.",
                parts=[atlas.components[c].name for _, cs in columns for c in cs],
            )
        )

        # 3. Where work comes in.
        entry_parts = parts_in(_ENTRY)
        if flows or entry_parts:
            kinds = Counter(f.label for f in flows)
            ways = _list([_plural(n, label) for label, n in kinds.most_common()], 5)
            declared = Counter(f.path for f in flows)
            how = _sentences(
                narratives.get(NarrativeTopic.REQUEST_LIFECYCLE) or narratives.get(NarrativeTopic.CLI_USAGE), 2
            )
            body = (
                (f"There are {ways} — every way something outside asks this code to do work. " if ways else "")
                + (
                    "They are declared in " + _list([_code(p) for p, _ in declared.most_common(3)], 3) + "."
                    if declared
                    else ""
                )
            ).strip()
            stops.append(
                Stop(
                    "entry",
                    "Where work comes in",
                    ((how + "\n\n") if how else "") + (body or "These parts take work in from outside."),
                    parts=[atlas.components[c].name for c in entry_parts],
                    files=[TourFile(p, _plural(n, "way") + " in") for p, n in declared.most_common(5)],
                )
            )

        # 4. One real request, end to end.
        flow = self._pick(flows, Counter(f.path for f in flows))
        if flow is not None:
            chain = [flow.steps[i] for i in flow.chain]
            first, last = chain[0], chain[-1]
            through = [s for s in chain[1:-1]][:3]
            ending = {
                "data": "where it reads or writes data",
                "outside": "where it calls a service outside the code",
            }.get(flow.ends or "", "the deepest function the recorded calls reach")
            body = (
                f"Follow {_code(flow.name)} ({flow.label}). It arrives at {_code(first.qname)} in {_code(first.path)}"
                + (
                    ", passes through " + _list([_code(s.qname) for s in through], 3)
                    if through
                    else ""
                )
                + f", and ends at {_code(last.qname)} in {_code(last.path)}, {ending}."
                + f" That is {_plural(len(chain), 'step')}"
                + (f" across {_list(named, 4)}" if len(named := [p for p in flow.parts() if p != UNMAPPED]) > 1 else "")
                + ". The flow below plays it; pick a step to read its code."
            )
            seen: list[str] = []
            for s in chain:
                if s.path not in seen:
                    seen.append(s.path)
            stops.append(
                Stop(
                    "flow",
                    f"Follow one request: {flow.name}",
                    body,
                    parts=flow.parts(),
                    files=[TourFile(p) for p in seen[:8]],
                    flow=flow.id,
                )
            )

        # 5. The core.
        core = parts_in(_CORE)
        if core:
            top = atlas.components[core[0]]
            desc = (top.description or "").strip().rstrip(".")
            what = f": {desc[0].lower() + desc[1:]}" if desc else ""
            body = (
                f"The core logic is in {_code(top.name)} ({_plural(members[core[0]], 'file')}){what}. "
                if len(core) == 1
                else f"The core logic is in {_list([_code(atlas.components[c].name) for c in core], 4)}. "
                + (f"The largest is {_code(top.name)} ({_plural(members[core[0]], 'file')}){what}. ")
            ) + "The files below are the ones the rest of the code leans on most."
            stops.append(
                Stop(
                    "core",
                    "The core",
                    body,
                    parts=[atlas.components[c].name for c in core],
                    files=most_imported(core, 5),
                )
            )

        # 6. Where the data lives, and what it talks to outside.
        data_parts = parts_in(_DATA)
        stores = [n for n in atlas.nodes if n.fact == EntityKind.DATASTORE]
        outside = [n for n in atlas.nodes if n.fact == EntityKind.EXTERNAL_API]
        reached = {i for i, n in enumerate(atlas.nodes) if n.fact in (EntityKind.DATASTORE, EntityKind.EXTERNAL_API)}
        if data_parts or stores or outside:
            said = _sentences(
                narratives.get(NarrativeTopic.DATA_MODEL) or narratives.get(NarrativeTopic.INTEGRATIONS), 2
            )
            facts = []
            if stores:
                facts.append("It keeps data in " + _list([_code(n.path) for n in stores], 4) + ".")
            if outside:
                facts.append("It talks to " + _list([_code(n.path) for n in outside], 4) + ".")
            touching = Counter(
                atlas.nodes[a].path
                for a, b in atlas.edges
                if b in reached and not atlas.nodes[a].fact and atlas.nodes[a].kind != "test"
            )
            listed = [TourFile(p, "talks to " + _plural(n, "store or service", "stores or services")) for p, n in touching.most_common(4)]
            for f in most_imported(data_parts, 3):
                if all(f.path != g.path for g in listed):
                    listed.append(f)
            stops.append(
                Stop(
                    "data",
                    "Where the data lives",
                    "\n\n".join(x for x in (said, " ".join(facts)) if x)
                    or "These parts hold the data and reach the services outside the code.",
                    parts=[atlas.components[c].name for c in data_parts],
                    files=listed[:6],
                )
            )

        # 7. What everyone uses.
        helper_parts = parts_in(_HELPERS)
        helpers = most_imported(helper_parts, 5) if helper_parts else []
        if helpers:
            stops.append(
                Stop(
                    "helpers",
                    "What everything leans on",
                    f"The shared helpers in {_list([_code(atlas.components[c].name) for c in helper_parts], 4)} "
                    "are imported from all over the code. They change rarely and break widely: read them once, "
                    "early, and expect most code to use them rather than reinvent them.",
                    parts=[atlas.components[c].name for c in helper_parts],
                    files=helpers,
                )
            )

        # 8. Where an edit hurts.
        ranked, _total = await RiskService(self.db, kb).rank(limit=6)
        ranked = [r for r in ranked if r.reach >= 2][:5]
        if ranked:
            untested = sum(1 for r in ranked if r.tests == 0)
            stops.append(
                Stop(
                    "care",
                    "Where an edit hurts",
                    "These files reach the most of the code: a change to one is felt in every file that depends "
                    "on it, directly or not."
                    + (
                        f" {_plural(untested, 'of them has', 'of them have')} no test reaching {('it' if untested == 1 else 'them')}."
                        if untested
                        else " Each has a test reaching it."
                    )
                    + " Before editing one, look at what depends on it — in the graph, or with `before_edit`.",
                    parts=sorted({r.component for r in ranked if r.component}),
                    files=[
                        TourFile(
                            r.path,
                            f"reaches {_plural(r.reach, 'file')}" + ("" if r.tests else ", no test"),
                        )
                        for r in ranked
                    ],
                )
            )

        # 9. Run it yourself, when the reading kept the files that say how.
        book = await RunbookService(self.db, kb).build()
        if book.available and (book.install or book.run or book.test):
            needs = [f"{n.what} {n.version}".strip() if n.version else n.what for n in book.needs]
            lines = [f"It needs {_list(needs, 5)}." if needs else ""]
            steps = [("Install", book.install), ("Run", book.run), ("Test", book.test)]
            lines += [f"- {label}: {_code(chosen[0].command)}" for label, chosen in steps if chosen]
            missing = [e.name for e in book.env if e.missing]
            if missing:
                lines.append(
                    f"\nThe code reads {_plural(len(missing), 'variable')} no template declares, "
                    + _list([_code(m) for m in missing], 4)
                    + ": set them before it starts."
                )
            sources: list[TourFile] = []
            for label, chosen in steps:
                if chosen and all(f.path != chosen[0].source for f in sources):
                    sources.append(TourFile(chosen[0].source, f"how to {label.lower()} it"))
            stops.append(
                Stop(
                    "run",
                    "Run it yourself",
                    "\n".join(line for line in lines if line),
                    parts=[SETUP] if any(c.name == SETUP for c in atlas.components) else [],
                    files=sources,
                )
            )

        # 10. Where to go next.
        stops.append(
            Stop(
                "next",
                "Where to go next",
                "Ask the code anything — answers cite the lines they come from. "
                + (f"Every one of the {_plural(len(flows), 'way')} in can be followed in the Flows tab. " if flows else "")
                + "Before you change something, review the change against this reading; and if you work with a "
                "coding agent, give it the instruction file from the codebase page.",
            )
        )
        return tour

    async def _narratives(self) -> dict[str, str]:
        rows = (
            await self.db.execute(
                select(KBNarrative.topic, KBNarrative.content_md).where(KBNarrative.kb_id == self.kb.id)
            )
        ).all()
        return {str(t): c for t, c in rows}

    @staticmethod
    def _pick(flows: list[Flow], declared: Counter[str]) -> Flow | None:
        """The request most worth following: one that reaches data or a service, a route
        before a command, three steps or more, from the file most ways in are declared in
        (the code's main surface, not a corner of it), and among those the one that
        crosses the most parts."""
        if not flows:
            return None

        def score(f: Flow) -> tuple:
            kind = _FLOW_PREFERENCE.index(f.kind) if f.kind in _FLOW_PREFERENCE else len(_FLOW_PREFERENCE)
            n = len(f.chain)
            parts = len([p for p in f.parts() if p != UNMAPPED])
            return (f.ends is None, n < 3, kind, -declared[f.path], -parts, -min(n, 7), f.name)

        return min(flows, key=score)


__all__ = ["Stop", "Tour", "TourFile", "TourService"]
