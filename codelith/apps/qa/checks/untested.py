"""
The ways in that no test reaches: routes, commands and jobs, ranked by what they touch.

One finding per file that declares them, not one per route: a router with twelve
untested endpoints is one piece of work. Its title names no count, so the finding is
the same finding next run when one of them gets a test.
"""

from __future__ import annotations

from collections import defaultdict

from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding
from codelith.knowledge.flows import FlowService
from codelith.knowledge.risk import RiskService

AREAS = frozenset({"tests"})
TITLE = "Routes and commands no test reaches"
RULES = {"tests.untested-entry": "Entry points no test reaches"}

_NOUN = {
    "route": ("route", "routes"),
    "cli_command": ("command", "commands"),
    "scheduled_task": ("scheduled job", "scheduled jobs"),
    "entrypoint": ("entry point", "entry points"),
    "event": ("event handler", "event handlers"),
}


async def run(ctx: RunContext) -> list[Finding]:
    flows = await FlowService(ctx.db, ctx.kb).flows()
    if not flows:
        return []
    risk = {r.path: r for r in (await RiskService(ctx.db, ctx.kb).rank(limit=1_000_000))[0]}
    scoped = {f.path for f in ctx.files}
    by_file: dict[str, list] = defaultdict(list)
    for flow in flows:
        r = risk.get(flow.path)
        if flow.path in scoped and r is not None and r.tests == 0 and r.kind != "test":
            by_file[flow.path].append(flow)
    out: list[Finding] = []
    for path, untested in sorted(by_file.items()):
        reaching = [f for f in untested if f.ends in ("data", "outside")]
        kinds = {f.kind for f in untested}
        one, many = _NOUN.get(next(iter(kinds)) if len(kinds) == 1 else "", ("entry point", "entry points"))
        severity = "medium" if reaching else "low"
        names = ", ".join(f"`{f.name}`" for f in untested[:6]) + (f" and {len(untested) - 6} more" if len(untested) > 6 else "")
        out.append(
            Finding(
                rule="tests.untested-entry",
                area="tests",
                severity=severity,
                title=f"No test reaches the {many} in `{path.rsplit('/', 1)[-1]}`",
                message=f"{len(untested)} {one if len(untested) == 1 else many} declared here, and no test file reaches "
                f"this file: {names}."
                + (
                    f" {len(reaching)} of them reach data or an outside service, so a change here can lose or "
                    "corrupt data with nothing to say so."
                    if reaching
                    else ""
                ),
                fix="Add a test per route that calls it the way a client would and checks the answer, starting with "
                "the ones that write data. QA's test design (Q5) can draft them.",
                path=path,
                line=min((f.line or 0) for f in untested) or None,
                source="check",
                evidence={"entries": [{"kind": f.kind, "name": f.name, "line": f.line, "ends": f.ends} for f in untested]},
            )
        )
    return out


__all__ = ["AREAS", "TITLE", "run"]
