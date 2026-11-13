"""
What each finding touches, from what the reading already knows.

A linter stops at the line. This adds the part the file is in, how many files depend
on it, whether a test reaches it, the written pages that cite it, and — from the
function the finding is in — the routes whose calls reach it and whether any of them
can be called without signing in. An injection behind a public route and the same line
in a script nobody runs are not the same finding.
"""

from __future__ import annotations

from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding
from codelith.apps.qa.routes import route_access
from codelith.knowledge.risk import RiskService

#: How far a security finding behind a public route is raised.
_RAISE = {"high": "critical", "medium": "high"}


async def attach(ctx: RunContext, findings: list[Finding]) -> None:
    paths = {f.path for f in findings if f.path}
    if not paths:
        return
    risk = {r.path: r for r in (await RiskService(ctx.db, ctx.kb).rank(limit=1_000_000))[0]}
    ra = await route_access(ctx)
    # Every flow, routes or not, that passes through a file: the fallback when a finding
    # is not inside a function (module code, a config file).
    by_file: dict[str, list] = {}
    for flow in ra.flows.values():
        for path in {flow.path, *(s.path for s in flow.steps)} & paths:
            by_file.setdefault(path, []).append(flow)

    for f in findings:
        if not f.path:
            continue
        r = risk.get(f.path)
        qname = ra.enclosing(f.path, f.line)
        routes = ra.reaching(f.path, f.line, qname) if qname else []
        entries = by_file.get(f.path, []) if not qname else [x for x in ra.flows.values() if any(s.path == f.path and s.qname == qname for s in x.steps)]
        exposure = ra.exposure(routes) if routes else ("entry" if entries else "internal")
        f.impact = {
            "part": r.component if r else None,
            "kind": r.kind if r else None,
            "function": qname,
            "reach": r.reach if r else 0,
            "direct": r.direct if r else 0,
            "tests": r.tests if r else 0,
            "pages": r.pages if r else 0,
            "routes": [x.name for x in routes][:8],
            "route_count": len(routes),
            "entries": len(entries),
            #: `public` (a route anyone can call reaches it), `authenticated`, `entry`
            #: (a command or job), or `internal`.
            "exposure": exposure,
        }
        if f.evidence.get("chain"):
            f.impact["chain"] = f.evidence["chain"]
        # A security finding a public route reaches is worse than the same line elsewhere.
        if f.area == "security" and exposure == "public" and f.severity in _RAISE and "raised_from" not in f.evidence:
            if not f.rule.startswith(("security.input-to-", "security.route-")):
                f.evidence["raised_from"] = f.severity
                f.severity = _RAISE[f.severity]
        if f.evidence.get("raised_from"):
            f.impact["raised_from"] = f.evidence["raised_from"]


__all__ = ["attach"]
