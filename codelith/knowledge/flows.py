"""
Flows: the path a request takes through the code, function by function.

For every way into the code — an API route, a command, a scheduled job, an event, an
entry point — this follows the calls the reading recorded (`graph_calls`) from the
function that handles it, breadth first, until it reaches the code that touches data
or an outside service. The shortest such path is the flow's *chain*: what a reader
means by "what happens when somebody calls POST /orders".

Derived on demand from what analysis already stored, never at analysis time: the call
graph, the facts and the map are kept per reading, so every reading — including ones
made before this existed — has its flows without being read again. Cached per reading,
which never changes once it is finished.

Calls are only as good as their resolution (`knowledge/graph.py` resolves a call when
the callee is unambiguous), so a chain can stop short of the data; it then ends at the
deepest function reached and says so, rather than guessing the rest.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.knowledge.atlas import AtlasService
from codelith.knowledge.constants import EntityKind
from codelith.models.graph import GraphCall, GraphSymbol
from codelith.models.knowledge import KBEntity, KnowledgeBase

#: Ways into the code, in the order a list of them reads best.
ENTRY_KINDS: tuple[str, ...] = (
    EntityKind.ROUTE,
    EntityKind.CLI_COMMAND,
    EntityKind.SCHEDULED_TASK,
    EntityKind.EVENT,
    EntityKind.ENTRYPOINT,
)
_ENTRY_LABEL = {
    EntityKind.ROUTE: "route",
    EntityKind.CLI_COMMAND: "command",
    EntityKind.SCHEDULED_TASK: "scheduled job",
    EntityKind.EVENT: "event",
    EntityKind.ENTRYPOINT: "entry point",
}

#: How far a flow is followed, and how much of it is kept. Past this a flow is a map of
#: the codebase, not of a request.
MAX_DEPTH = 7
MAX_STEPS = 40
MAX_FLOWS = 150

_cache: dict[tuple[int, str], list[Flow]] = {}


@dataclass(slots=True)
class Step:
    qname: str
    path: str
    line: int | None
    depth: int
    parent: int | None
    kind: str | None
    part: str | None
    #: `data` or `outside` when this function is where the flow touches them.
    ends: str | None = None


@dataclass(slots=True)
class Flow:
    id: str
    kind: str
    name: str
    path: str
    line: int | None
    steps: list[Step] = field(default_factory=list)
    #: Step indexes from the entry to where it ends.
    chain: list[int] = field(default_factory=list)
    #: `data`, `outside`, or None when the recorded calls stop before either.
    ends: str | None = None

    @property
    def label(self) -> str:
        return _ENTRY_LABEL.get(self.kind, self.kind)

    def parts(self) -> list[str]:
        """The parts along the chain, in order, each once."""
        out: list[str] = []
        for i in self.chain:
            part = self.steps[i].part
            if part and (not out or out[-1] != part):
                out.append(part)
        return out

    def summary(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "name": self.name,
            "path": self.path,
            "line": self.line,
            "steps": len(self.steps),
            "chain": len(self.chain),
            "ends": self.ends,
            "parts": self.parts(),
        }

    def to_dict(self) -> dict:
        return {**self.summary(), "all_steps": [asdict(s) for s in self.steps], "chain_steps": self.chain}

    def brief(self) -> str:
        """The chain as prose an agent reads: one line per step, nearest first."""
        if not self.chain:
            return f"{self.name} ({self.label} in {self.path}): no handler was found in the call graph."
        lines = [f"{self.name} — {self.label}, declared in {self.path}" + (f":{self.line}" if self.line else "")]
        for depth, i in enumerate(self.chain):
            s = self.steps[i]
            where = f"{s.path}:{s.line}" if s.line else s.path
            tail = {"data": "  ← reads or writes data", "outside": "  ← calls an outside service"}.get(s.ends or "", "")
            lines.append(f"  {'  ' * depth}→ {s.qname}  ({where}{', ' + s.part if s.part else ''}){tail}")
        if not self.ends:
            lines.append(
                "  (The recorded calls stop here. Calls are traced only where the callee is unambiguous, "
                "so the request may go further than this.)"
            )
        others = len(self.steps) - len(self.chain)
        if others > 0:
            lines.append(f"  It also calls {others} other function(s) along the way.")
        return "\n".join(lines)


def flow_id(kind: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", f"{kind} {name}".lower()).strip("-")
    return slug[:120] or "flow"


class FlowService:
    def __init__(self, db: AsyncSession, kb: KnowledgeBase) -> None:
        self.db = db
        self.kb = kb

    async def flows(self) -> list[Flow]:
        key = (self.kb.id, str(self.kb.completed_at or ""))
        hit = _cache.get(key)
        if hit is not None:
            return hit
        built = await self._build()
        if len(_cache) > 16:
            _cache.clear()
        _cache[key] = built
        return built

    async def find(self, query: str) -> Flow | None:
        """A flow by id, by name (`POST /orders`, a command), or by its handler or file."""
        q = (query or "").strip().lower()
        if not q:
            return None
        flows = await self.flows()
        for test in (
            lambda f: f.id == q or f.name.lower() == q,
            lambda f: q in f.name.lower(),
            lambda f: any(q == s.qname.lower() or s.qname.lower().endswith("." + q) for s in f.steps[:1]),
            lambda f: f.path.lower().endswith(q),
        ):
            hits = [f for f in flows if test(f)]
            if hits:
                return max(hits, key=lambda f: len(f.chain))
        return None

    # ── building ───────────────────────────────────────────────────────────

    async def _build(self) -> list[Flow]:
        kb = self.kb
        scope = (GraphSymbol.project_id == kb.project_id, GraphSymbol.kb_id == kb.id)
        symbols = (
            await self.db.execute(
                select(GraphSymbol.path, GraphSymbol.qname, GraphSymbol.name, GraphSymbol.kind, GraphSymbol.line).where(
                    *scope
                )
            )
        ).all()
        by_path: dict[str, list[tuple[str, str | None, str | None, int | None]]] = {}
        kinds: dict[tuple[str, str], tuple[str | None, int | None]] = {}
        for path, qname, name, kind, line in symbols:
            by_path.setdefault(path, []).append((qname, name, kind, line))
            kinds[(path, qname)] = (kind, line)
        for rows in by_path.values():
            rows.sort(key=lambda r: r[3] or 0)

        calls = (
            await self.db.execute(
                select(GraphCall.src_path, GraphCall.src_qname, GraphCall.dst_path, GraphCall.dst_qname).where(
                    GraphCall.project_id == kb.project_id, GraphCall.kb_id == kb.id
                )
            )
        ).all()
        out: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for sp, sq, dp, dq in calls:
            out.setdefault((sp, sq), []).append((dp, dq))

        atlas = await AtlasService(self.db, kb).build()
        part_of: dict[str, str] = {}
        ends_of: dict[str, str] = {}
        for node in atlas.nodes:
            if node.fact:
                continue
            part_of[node.path] = atlas.components[node.component].name
            if node.kind == "data":
                ends_of[node.path] = "data"
        for a, b in atlas.edges:
            na, nb = atlas.nodes[a], atlas.nodes[b]
            if not na.fact and nb.fact:
                if nb.kind == "store":
                    ends_of.setdefault(na.path, "data")
                elif nb.kind == "external":
                    ends_of.setdefault(na.path, "outside")

        entries = (
            await self.db.execute(
                select(KBEntity.kind, KBEntity.name, KBEntity.source_path, KBEntity.source_line, KBEntity.data_json)
                .where(KBEntity.kb_id == kb.id, KBEntity.kind.in_([str(k) for k in ENTRY_KINDS]))
                .limit(MAX_FLOWS * 2)
            )
        ).all()

        flows: list[Flow] = []
        seen: set[str] = set()
        for kind, name, path, line, data in entries:
            if not path:
                continue
            start = self._start(kind, path, line, data or {}, by_path)
            fid = flow_id(kind, name)
            if fid in seen:
                continue
            seen.add(fid)
            flow = Flow(id=fid, kind=str(kind), name=name, path=path, line=line)
            if start is not None:
                self._walk(flow, start, out, kinds, part_of, ends_of)
            flows.append(flow)
            if len(flows) >= MAX_FLOWS:
                break

        order = {str(k): i for i, k in enumerate(ENTRY_KINDS)}
        flows.sort(key=lambda f: (order.get(f.kind, 9), -len(f.chain), f.name))
        return flows

    @staticmethod
    def _start(kind: str, path: str, line: int | None, data: dict, by_path) -> tuple[str, str] | None:
        """The function that handles an entry: named by the fact when it says, otherwise
        the one declared at or just after the fact's line (a decorator sits above it)."""
        rows = by_path.get(path) or []
        handler = str(data.get("handler") or "")
        if handler:
            for qname, name, _kind, _line in rows:
                if qname == handler or name == handler.split(".")[-1]:
                    return path, qname
        if kind == EntityKind.ENTRYPOINT:
            for wanted in ("main", "run", "cli", "app"):
                for qname, name, _kind, _line in rows:
                    if name == wanted:
                        return path, qname
        if line is not None:
            after = [r for r in rows if (r[3] or 0) >= line and (r[3] or 0) - line <= 6]
            if after:
                return path, after[0][0]
            before = [r for r in rows if (r[3] or 0) <= line]
            if before:
                return path, before[-1][0]
        return (path, rows[0][0]) if rows else None

    @staticmethod
    def _walk(flow: Flow, start, out, kinds, part_of, ends_of) -> None:
        index: dict[tuple[str, str], int] = {}

        def add(node: tuple[str, str], depth: int, parent: int | None) -> int:
            kind, line = kinds.get(node, (None, None))
            path = node[0]
            flow.steps.append(
                Step(
                    qname=node[1],
                    path=path,
                    line=line,
                    depth=depth,
                    parent=parent,
                    kind=kind,
                    part=part_of.get(path),
                    ends=ends_of.get(path),
                )
            )
            index[node] = len(flow.steps) - 1
            return index[node]

        add(start, 0, None)
        queue = deque([start])
        first_end: int | None = None
        while queue and len(flow.steps) < MAX_STEPS:
            node = queue.popleft()
            i = index[node]
            step = flow.steps[i]
            if step.ends and i != 0:
                if first_end is None:
                    first_end = i
                continue  # where the request meets data or the outside, it is followed no further
            if step.depth >= MAX_DEPTH:
                continue
            for nxt in out.get(node, ()):
                if nxt in index or len(flow.steps) >= MAX_STEPS:
                    continue
                add(nxt, step.depth + 1, i)
                queue.append(nxt)

        if first_end is None and flow.steps[0].ends:
            first_end = 0
        end = first_end
        if end is None:
            # No data reached: the deepest function the recorded calls lead to.
            end = max(range(len(flow.steps)), key=lambda k: (flow.steps[k].depth, -k))
        chain: list[int] = []
        at: int | None = end
        while at is not None:
            chain.append(at)
            at = flow.steps[at].parent
        flow.chain = list(reversed(chain))
        flow.ends = flow.steps[first_end].ends if first_end is not None else None


__all__ = ["ENTRY_KINDS", "Flow", "FlowService", "Step", "flow_id"]
