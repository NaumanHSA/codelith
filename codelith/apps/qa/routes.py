"""
Who can reach what: every route's guard, and the functions each route's calls pass
through. Worked out once per run and shared by the checks and by impact.

A route is **guarded** when its handler, its router or its class requires a signed-in
caller, or a function named for authentication is on its path; **behind the app** when
something guards every request (an auth middleware) and nothing about the route itself
says so; **public by design** when its path is one that has to be (sign-in, health,
webhooks, docs); and **open** otherwise. Guards are recognised by name, so the verdict
is *likely*: QA says how it decided.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from sqlalchemy import select

from codelith.apps.qa.context import RunContext
from codelith.knowledge.constants import EntityKind
from codelith.knowledge.flows import Flow, FlowService
from codelith.languages import registry
from codelith.languages.base import FlowFacts
from codelith.languages.providers._python_routes import AUTH
from codelith.models.graph import GraphSymbol
from codelith.models.knowledge import KBEntity

#: Paths that are public on purpose. A route matching one is never reported as open.
PUBLIC_BY_DESIGN = re.compile(
    r"(login|logout|signin|sign-in|signup|sign-up|register|token|refresh|oauth|callback|sso|password[-_]?reset|forgot|verify|"
    r"health|healthz|ready|readiness|live|liveness|ping|status|version|metrics|webhook|hooks?|public|docs|openapi|swagger|redoc|"
    r"static|assets|favicon|robots)",
    re.IGNORECASE,
)
_WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(slots=True)
class Access:
    #: `guarded`, `app` (behind an app-wide guard), `public` (public by design) or `open`.
    status: str
    #: What decided it, in a phrase: the dependency, the router, the middleware.
    evidence: str
    method: str = ""
    path: str = ""


@dataclass(slots=True)
class RouteAccess:
    routes: list[Flow] = field(default_factory=list)
    access: dict[str, Access] = field(default_factory=dict)
    #: `(path, qname)` to the ids of the route flows whose calls pass through it.
    through: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    #: Every flow, routes or not, by id.
    flows: dict[str, Flow] = field(default_factory=dict)
    facts: dict[str, FlowFacts] = field(default_factory=dict)
    app_guard: tuple[str, str] | None = None
    #: Guarding type aliases from every file: a handler parameter typed with one is guarded.
    aliases: dict[str, str] = field(default_factory=dict)
    #: path to `(qname, line, end_line)`, innermost last when sorted by span.
    symbols: dict[str, list[tuple[str, int, int]]] = field(default_factory=dict)

    def enclosing(self, path: str, line: int | None) -> str | None:
        """The innermost function or method holding `line`."""
        if not line:
            return None
        best: tuple[str, int, int] | None = None
        for qname, start, end in self.symbols.get(path, []):
            if start <= line <= end and (best is None or end - start <= best[2] - best[1]):
                best = (qname, start, end)
        return best[0] if best else None

    def reaching(self, path: str, line: int | None, qname: str | None = None) -> list[Flow]:
        """The route flows whose calls reach the function holding this line."""
        q = qname or self.enclosing(path, line)
        if not q:
            return []
        return [self.flows[i] for i in self.through.get((path, q), [])]

    def exposure(self, flows: list[Flow]) -> str:
        if not flows:
            return "internal"
        statuses = {self.access[f.id].status for f in flows if f.id in self.access}
        if statuses & {"open", "public"}:
            return "public"
        if statuses:
            return "authenticated"
        return "entry"


async def route_access(ctx: RunContext) -> RouteAccess:
    """Worked out once per run and kept on the context."""
    cached = ctx.cache.get("routes")
    if cached is not None:
        return cached
    ra = RouteAccess()
    kb = ctx.kb

    rows = (
        await ctx.db.execute(
            select(GraphSymbol.path, GraphSymbol.qname, GraphSymbol.kind, GraphSymbol.line, GraphSymbol.end_line).where(
                GraphSymbol.project_id == kb.project_id, GraphSymbol.kb_id == kb.id
            )
        )
    ).all()
    for path, qname, kind, line, end in rows:
        if line and end and str(kind) in ("function", "method", "constructor"):
            ra.symbols.setdefault(path, []).append((qname, int(line), int(end)))

    # Every source file's guards and sinks, from the files the reading kept.
    items = []
    for f in ctx.all_files:
        provider = registry.for_path(f.path) if f.kind is None else None
        if provider is not None:
            items.append((provider, f.path, await ctx.text(f)))

    def read_all() -> dict[str, FlowFacts]:
        out: dict[str, FlowFacts] = {}
        for provider, path, text in items:
            facts = provider.flow_facts(path, text)
            if facts is not None:
                out[path] = facts
        return out

    ra.facts = await asyncio.to_thread(read_all)
    for path, facts in sorted(ra.facts.items()):
        if facts.guards.app and ra.app_guard is None:
            ra.app_guard = (path, facts.guards.app)
        ra.aliases.update(facts.guards.aliases)

    entries = {
        name: data or {}
        for name, data in (
            await ctx.db.execute(
                select(KBEntity.name, KBEntity.data_json).where(KBEntity.kb_id == kb.id, KBEntity.kind == str(EntityKind.ROUTE))
            )
        ).all()
    }
    for flow in await FlowService(ctx.db, kb).flows():
        ra.flows[flow.id] = flow
        if flow.kind != str(EntityKind.ROUTE):
            continue
        ra.routes.append(flow)
        data = entries.get(flow.name, {})
        method = str(data.get("method") or flow.name.split(" ", 1)[0]).upper()
        route_path = str(data.get("path") or (flow.name.split(" ", 1)[1] if " " in flow.name else flow.name))
        ra.access[flow.id] = _decide(ra, flow, data, method, route_path)
        for step in flow.steps:
            ra.through.setdefault((step.path, step.qname), []).append(flow.id)
    ctx.cache["routes"] = ra
    return ra


def _decide(ra: RouteAccess, flow: Flow, data: dict, method: str, route_path: str) -> Access:
    facts = ra.facts.get(flow.path)
    handler = flow.steps[0].qname if flow.steps else str(data.get("handler") or "")
    if facts is not None:
        guards = facts.guards
        cls = handler.rsplit(".", 1)[0] + ".*" if "." in handler else ""
        for key in (handler, handler.rsplit(".", 1)[-1], cls):
            if key and key in guards.handlers:
                return Access("guarded", guards.handlers[key], method, route_path)
        for name in guards.uses.get(handler, []):
            if name in ra.aliases:
                return Access("guarded", f"{name} = {ra.aliases[name]}", method, route_path)
        router = str(data.get("router") or "")
        if router and router in guards.routers:
            return Access("guarded", f"{router}: {guards.routers[router]}", method, route_path)
        if "*" in guards.routers:
            return Access("guarded", guards.routers["*"], method, route_path)
    for step in flow.steps[1:]:
        if AUTH.search(step.qname.rsplit(".", 1)[-1]):
            return Access("guarded", f"calls {step.qname}", method, route_path)
    if PUBLIC_BY_DESIGN.search(route_path):
        return Access("public", "its path is one that is public on purpose", method, route_path)
    if ra.app_guard is not None:
        return Access("app", f"{ra.app_guard[1]} ({ra.app_guard[0]})", method, route_path)
    return Access("open", "nothing on its path requires a signed-in caller", method, route_path)


def writes(access: Access) -> bool:
    return access.method in _WRITES


def chain_of(flow: Flow, path: str, qname: str) -> list[str]:
    """The calls from the route's handler to `qname`, by their names."""
    by_index = {i: s for i, s in enumerate(flow.steps)}
    target = next((i for i, s in enumerate(flow.steps) if s.path == path and s.qname == qname), None)
    if target is None:
        return [flow.name]
    out: list[str] = []
    i: int | None = target
    while i is not None:
        out.append(by_index[i].qname)
        i = by_index[i].parent
    return [flow.name, *reversed(out)]


__all__ = ["PUBLIC_BY_DESIGN", "Access", "RouteAccess", "chain_of", "route_access", "writes"]

