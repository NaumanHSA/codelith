"""
Thorough: the model reads the riskiest code, and every claim it makes is checked.

Rules see patterns; a model can see that a refund is issued before the payment is
confirmed. It can also invent a problem with complete confidence. So:

1. **What it reads is chosen, not everything.** Functions ranked by how much depends on
   them, whether a test reaches them, whether a route reaches them (more if anyone can
   call it), and whether they touch data or an outside service. A budget
   (`QA_REVIEW_TARGETS`), said in the results.
2. **A claim must quote its line.** The quote is looked for at the line it names, or
   two lines either side; a claim whose quote is not there is dropped and counted.
3. **A second call judges each surviving claim**, seeing only the claim and the code.
   Only "real" is kept. What is kept is marked *suspected*: worth reading, not proof.
4. A claim at a line a rule or check already flagged in the same area is dropped there:
   the rule said it with certainty.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

import structlog

from codelith.apps.qa.areas import AREA_BY_ID
from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding
from codelith.apps.qa.routes import chain_of, route_access
from codelith.config import get_settings
from codelith.core.cancellation import JobCancelled
from codelith.knowledge.risk import RiskService
from codelith.languages import registry

logger = structlog.get_logger(__name__)

AREAS = frozenset({"security", "leakage", "errors", "breaks", "performance"})
TITLE = "The model's review of the riskiest code, each claim checked"
RULES = {f"review.{a}": "Found in review" for a in AREAS}

#: Functions shorter than this say too little to review; longer ones are cut here.
_MIN_LINES = 4
_MAX_LINES = 220
_SEVERITIES = ("critical", "high", "medium", "low")
_SPACE = re.compile(r"\s+")


def _json(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def numbered(lines: list[str], first: int, last: int) -> str:
    return "\n".join(f"{n:>5} | {lines[n - 1]}" for n in range(first, last + 1) if 0 < n <= len(lines))


def anchor(lines: list[str], line: int, quote: str, start: int, end: int) -> int | None:
    """The line the quote is really on: the one named, or within two of it, inside the function."""
    want = _SPACE.sub("", quote or "")
    if len(want) < 4:
        return None
    for n in (line, line - 1, line + 1, line - 2, line + 2):
        if start <= n <= end and 0 < n <= len(lines) and want in _SPACE.sub("", lines[n - 1]):
            return n
    return None


async def _targets(
    ctx: RunContext,
    budget: int | None = None,
    keep: Callable[[str], bool] | None = None,
    untested_only: bool = False,
) -> list[tuple[float, str, str, int, int]]:
    """
    `(score, path, qname, start, end)` for the functions worth the model's time, best
    first. `keep` narrows the files; `untested_only` skips files a test reaches.
    """
    budget = get_settings().QA_REVIEW_TARGETS if budget is None else budget
    ra = await route_access(ctx)
    risk = {r.path: r for r in (await RiskService(ctx.db, ctx.kb).rank(limit=1_000_000))[0]}
    scoped = {f.path for f in ctx.files if f.kind is None}
    ends = {(s.path) for flow in ra.flows.values() for s in flow.steps if s.ends in ("data", "outside")}
    out: list[tuple[float, str, str, int, int]] = []
    for path, symbols in ra.symbols.items():
        if path not in scoped:
            continue
        provider = registry.for_path(path)
        if provider is None or provider.is_test_file(path) or (keep is not None and not keep(path)):
            continue
        r = risk.get(path)
        if untested_only and r is not None and r.tests > 0:
            continue
        for qname, start, end in symbols:
            if end - start + 1 < _MIN_LINES:
                continue
            routes = ra.reaching(path, start, qname)
            score = (1 + (r.reach if r else 0)) * (1.5 if r and r.tests == 0 else 1.0)
            if routes:
                score *= 2.5 if ra.exposure(routes) == "public" else 1.8
            if path in ends:
                score *= 1.4
            out.append((score, path, qname, start, min(end, start + _MAX_LINES - 1)))
    out.sort(key=lambda t: (-t[0], t[1], t[3]))
    # One function per file at a time, so the budget is spread rather than spent on one module.
    picked: list[tuple[float, str, str, int, int]] = []
    seen: set[str] = set()
    for rnd in range(3):
        for t in out:
            if len(picked) >= budget:
                return picked
            if t in picked or (rnd == 0 and t[1] in seen):
                continue
            picked.append(t)
            seen.add(t[1])
    return picked


async def run(ctx: RunContext) -> list[Finding]:
    from codelith.llm import client as llm
    from codelith.llm.prompts.code_review_prompts import CODE_CONFIRM, CODE_REVIEW
    from codelith.llm.router import select_spec

    areas = [a for a in ("security", "leakage", "errors", "breaks", "performance") if a in ctx.areas]
    if not areas:
        return []
    ra = await route_access(ctx)
    targets = await _targets(ctx)
    if not targets:
        ctx.notes.append("The review found no function worth the model's time in scope.")
        return []

    area_text = "\n".join(f"- {a}: {AREA_BY_ID[a].label} — {'; '.join(AREA_BY_ID[a].looks_for)}" for a in areas)
    spec = select_spec("review")
    calls = claimed = unanchored = refuted = 0
    out: list[Finding] = []

    async def ask(messages: list[dict]) -> dict | None:
        nonlocal calls
        calls += 1
        return _json(await llm.chat_completion(messages, spec=spec))

    try:
        for _score, path, qname, start, end in targets:
            await ctx.checkpoint()
            lines = await ctx.lines(path)
            routes = ra.reaching(path, start, qname)
            context = []
            if routes:
                first = routes[0]
                access = ra.access.get(first.id)
                context.append(f"Reached from {', '.join(r.name for r in routes[:3])}: {' -> '.join(chain_of(first, path, qname))}.")
                if access:
                    context.append(
                        "Anyone can call that route." if access.status in ("open", "public") else "That route needs a signed-in caller."
                    )
            reply = await ask(
                CODE_REVIEW.render(
                    areas=area_text,
                    area_ids=", ".join(areas),
                    path=path,
                    function=qname,
                    context="\n".join(context) or "No route was seen reaching it.",
                    code=numbered(lines, start, end),
                )
            )
            for issue in (reply or {}).get("issues") or []:
                if not isinstance(issue, dict):
                    continue
                claimed += 1
                area = str(issue.get("area") or "")
                severity = str(issue.get("severity") or "medium").lower()
                try:
                    line = int(issue.get("line"))
                except (TypeError, ValueError):
                    line = 0
                at = anchor(lines, line, str(issue.get("quote") or ""), start, end)
                if area not in areas or at is None:
                    unanchored += 1
                    continue
                title = str(issue.get("title") or "").strip()[:200]
                why = str(issue.get("why") or "").strip()[:600]
                verdict = await ask(
                    CODE_CONFIRM.render(
                        line=str(at),
                        path=path,
                        title=title,
                        why=why,
                        code=numbered(lines, max(start, at - 15), min(len(lines), at + 15)),
                    )
                )
                if not verdict or str(verdict.get("verdict")) != "real":
                    refuted += 1
                    continue
                out.append(
                    Finding(
                        rule=f"review.{area}",
                        area=area,
                        severity=severity if severity in _SEVERITIES else "medium",
                        title=title or "A problem the review found",
                        message=why + (f" A second look agreed: {verdict.get('reason')}" if verdict.get("reason") else ""),
                        fix=str(issue.get("fix") or "").strip()[:500] or "See why it matters.",
                        path=path,
                        line=at,
                        confidence="suspected",
                        source="model",
                        evidence={"reviewed": qname},
                    )
                )
    except JobCancelled:
        raise
    except Exception as exc:  # the model is a guest: when it fails, the rest of the run still stands
        logger.warning("qa_review_failed", error=f"{type(exc).__name__}: {exc}")
        ctx.notes.append(f"The model could not be reached ({type(exc).__name__}): the review stopped after {calls} call(s).")

    ctx.notes.append(
        f"The model reviewed {len(targets)} function(s) chosen by risk, in {calls} call(s): {claimed} claim(s), "
        f"{unanchored} dropped because the quoted line was not where it said, {refuted} dropped on a second look, "
        f"{len(out)} kept."
    )
    return out


def drop_repeats(found: list[Finding]) -> list[Finding]:
    """A model's claim where a rule or check already found a problem in the same area goes."""
    certain = {(f.path, f.line, f.area) for f in found if f.source != "model"}
    return [f for f in found if f.source != "model" or (f.path, f.line, f.area) not in certain]


__all__ = ["AREAS", "RULES", "TITLE", "anchor", "drop_repeats", "numbered", "run"]
