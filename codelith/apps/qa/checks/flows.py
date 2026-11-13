"""
Security and leakage along the recorded calls: what a route lets in, and where request
data goes from there.

Three things a line-by-line rule cannot see:

- **A route that reaches data with no auth step on the way** — not the line, the
  absence of one. Only for routes that are not public on purpose, and not when an
  app-wide guard was found (said in the results instead).
- **Request data reaching a dangerous call** several functions down: a query, a shell,
  a file path, an outbound URL, a log. Where a line rule already flagged that call, the
  route and the path to it are added to that finding instead of a second one.
- **A response model carrying a secret**: a password hash or a private key in what the
  API sends back.
"""

from __future__ import annotations

import re

from codelith.apps.qa.areas import SEVERITY_RANK
from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding
from codelith.apps.qa.routes import chain_of, route_access, writes

AREAS = frozenset({"security", "leakage"})
TITLE = "Requests followed along the recorded calls"
RULES = {
    "security.route-unguarded": "Routes that reach data with no auth step",
    "security.input-to-sql": "Request data reaching SQL",
    "security.input-to-shell": "Request data reaching a shell",
    "security.input-to-code": "Request data run as code",
    "security.input-to-deserialize": "Request data deserialised",
    "security.input-to-file": "Request data choosing a file path",
    "security.input-to-url": "Request data choosing where the server connects",
    "leak.input-to-log": "Request data written to logs",
    "leak.response-secret-field": "Secrets in response models",
}

#: How bad a sink is, by whether an open route reaches it: (open, signed in only).
_SINKS: dict[str, tuple[str, str, str, str, str]] = {
    # kind: (area, open, signed-in, title, why)
    "sql": ("security", "critical", "high", "Request data can reach a SQL query",
            "A value from the request becomes part of the query text: a quote in it ends the string, and what follows runs as SQL."),
    "shell": ("security", "critical", "high", "Request data can reach a shell command",
              "A value from the request becomes part of a command line: `;` or `&&` in it runs a command of its own."),
    "code": ("security", "critical", "high", "Request data can be run as code",
             "A value from the request reaches `eval` or `exec`: whoever sends it chooses the code."),
    "deserialize": ("security", "critical", "high", "Request data is deserialised",
                    "Loading pickle or full YAML from the request lets the sender build objects that run code."),
    "file": ("security", "high", "medium", "Request data can choose a file path",
             "A path from the request reaches a call that opens, sends or deletes a file: `../` in it walks out of the folder meant."),
    "url": ("security", "high", "medium", "Request data can choose where the server connects",
            "The server fetches a URL the request supplied: it can be pointed at internal services and cloud metadata the caller cannot reach (SSRF)."),
    "log": ("leakage", "low", "low", "Request data is written to a log",
            "Whatever the request carried (passwords on a sign-up, personal details) is copied into logs that are kept and read widely."),
}
_FIX = {
    "sql": "Pass the values as parameters, never in the SQL text.",
    "shell": "Run the program with its arguments as a list, without a shell; check the value against what is allowed.",
    "code": "Do not evaluate input. Parse it (`json.loads`, `ast.literal_eval`) or map it to allowed operations.",
    "deserialize": "Accept JSON, or only load what this server wrote and signed.",
    "file": "Resolve the path and check it is inside the folder meant (`resolved.is_relative_to(base)`), or look the file up by an id.",
    "url": "Allow only the hosts it should reach, resolve them, and refuse private and link-local addresses.",
    "log": "Log what happened and an id, not the request's contents.",
}
#: Line rules that already flag the same call: their finding gets the route, not a twin.
MERGES = {
    "sql": ("py.sql-built", "ts.sql-built", "go.sql-built", "java.sql-built"),
    "shell": ("py.shell-injection", "ts.shell-injection", "go.shell-injection", "java.shell-injection"),
    "code": ("py.eval", "ts.eval"),
    "deserialize": ("py.unsafe-deserialization", "java.unsafe-deserialization"),
}

_SECRET_FIELD = re.compile(r"^(password|passwd|password_hash|hashed_password|pwd_hash|secret|client_secret|private_key|salt|otp|totp_secret|mfa_secret)$")
_TOKEN_FIELD = re.compile(r"^(access_token|refresh_token|token|api_key|apikey|session_token|reset_token)$")
_TOKEN_MODEL = re.compile(r"(token|auth|login|session|credential|key)", re.IGNORECASE)
_RESPONSE_NAME = re.compile(r"(Out|Response|Public|Read|View|Detail)$")


async def run(ctx: RunContext) -> list[Finding]:
    ra = await route_access(ctx)
    scoped = {f.path for f in ctx.files}
    out: list[Finding] = []

    if not ra.routes:
        ctx.notes.append("No routes were recorded for this reading, so no request was followed.")
    elif ra.app_guard is not None:
        ctx.notes.append(
            f"An app-wide guard was found ({ra.app_guard[1]} in {ra.app_guard[0]}): routes were not checked one by one "
            "for an auth step."
        )

    # Routes that reach data with nothing requiring a signed-in caller.
    if "security" in ctx.areas:
        for flow in ra.routes:
            access = ra.access.get(flow.id)
            if access is None or access.status != "open" or flow.path not in scoped or flow.ends != "data":
                continue
            data_step = next((s for s in flow.steps if s.ends == "data"), None)
            chain = chain_of(flow, data_step.path, data_step.qname) if data_step else [flow.name]
            out.append(
                Finding(
                    rule="security.route-unguarded",
                    area="security",
                    severity="high" if writes(access) else "medium",
                    title=f"`{flow.name}` {'changes' if writes(access) else 'reads'} data with no auth step",
                    message=(
                        f"Nothing on its path requires a signed-in caller, and it {'writes to' if writes(access) else 'reads from'} "
                        "the data: anyone who can reach the server can call it. The guard may live somewhere QA does not "
                        "recognise; if so, dismiss this with where."
                    ),
                    fix="Require a signed-in caller on the route (a dependency or decorator that checks the session or "
                    "token), or on its router so new routes are covered too.",
                    path=flow.path,
                    line=flow.line,
                    confidence="likely",
                    source="check",
                    evidence={"chain": chain, "route": flow.name},
                )
            )

    # Request data reaching a dangerous call.
    for path, facts in ra.facts.items():
        if path not in scoped:
            continue
        for sink in facts.sinks:
            area, open_sev, signed_sev, title, why = _SINKS[sink.kind]
            if area not in ctx.areas:
                continue
            qname = sink.function or ra.enclosing(path, sink.line)
            routes = ra.reaching(path, sink.line, qname)
            if not routes or qname is None:
                continue
            exposure = ra.exposure(routes)
            first = next((r for r in routes if ra.access.get(r.id) and ra.access[r.id].status in ("open", "public")), routes[0])
            chain = chain_of(first, path, qname)
            handler = first.steps[0].qname if first.steps else ""
            direct = qname == handler
            names = ", ".join(f"`{r.name}`" for r in routes[:3]) + (f" and {len(routes) - 3} more" if len(routes) > 3 else "")
            rule = f"{'leak' if area == 'leakage' else 'security'}.input-to-{sink.kind}"
            out.append(
                Finding(
                    rule=rule,
                    area=area,
                    severity=open_sev if exposure == "public" else signed_sev,
                    title=title,
                    message=f"{why} Reached from {names}"
                    + (" — a route anyone can call." if exposure == "public" else ", which need a signed-in caller.")
                    + ("" if direct else f" `{', '.join(sink.params)}` is handed down from the caller, so check what the route passes in."),
                    fix=_FIX[sink.kind],
                    path=path,
                    line=sink.line,
                    confidence="likely",
                    source="check",
                    evidence={"chain": chain, "route": first.name, "params": sink.params, "merge": list(MERGES.get(sink.kind, ()))},
                )
            )

    # Secrets in what the API sends back.
    if "leakage" in ctx.areas:
        answered = set().union(*(f.response_models for f in ra.facts.values())) if ra.facts else set()
        for path, facts in ra.facts.items():
            if path not in scoped:
                continue
            for model, fields in facts.models.items():
                if model not in answered and not _RESPONSE_NAME.search(model):
                    continue
                for name, line in fields:
                    secret = _SECRET_FIELD.match(name)
                    token = _TOKEN_FIELD.match(name) and not _TOKEN_MODEL.search(model)
                    if secret or token:
                        out.append(
                            Finding(
                                rule="leak.response-secret-field",
                                area="leakage",
                                severity="high" if secret else "medium",
                                title=f"`{model}` sends `{name}` to the client",
                                message=f"`{model}` is what a route answers with"
                                + (" (named as a response model)" if model in answered else "")
                                + f", and it has a `{name}` field: every caller of those routes receives it.",
                                fix=f"Remove `{name}` from the response model, or answer with a separate model that leaves it out.",
                                path=path,
                                line=line,
                                confidence="likely",
                                source="check",
                                evidence={"model": model, "field": name},
                            )
                        )
    return out


def merge(found: list[Finding]) -> list[Finding]:
    """
    Fold a flow finding into the line rule's finding at the same place: one finding,
    with the route that reaches it and its severity raised to the worse of the two.
    """
    by_place: dict[tuple[str | None, int | None], list[Finding]] = {}
    for f in found:
        by_place.setdefault((f.path, f.line), []).append(f)
    out: list[Finding] = []
    for f in found:
        merges = f.evidence.get("merge") if f.rule.startswith(("security.input-to-", "leak.input-to-")) else None
        if merges:
            twin = next((g for g in by_place.get((f.path, f.line), []) if g.rule in merges), None)
            if twin is not None:
                if SEVERITY_RANK.get(f.severity, 9) < SEVERITY_RANK.get(twin.severity, 9):
                    twin.evidence["raised_from"] = twin.severity
                    twin.severity = f.severity
                twin.evidence["chain"] = f.evidence.get("chain")
                twin.evidence["route"] = f.evidence.get("route")
                twin.message = f"{twin.message} {f.message.split('. ', 1)[-1]}"
                continue
        out.append(f)
    return out


__all__ = ["AREAS", "MERGES", "RULES", "TITLE", "merge", "run"]
