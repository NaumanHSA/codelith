"""
Designed tests: the model writes tests for code nothing tests, and for code a reviewer
suspects; the sandbox runs them; a failure is judged.

1. **What gets a test is chosen.** First the suspected findings worth reproducing (a
   test that fails proves more than a reviewer's opinion), then the riskiest functions
   no test reaches. A budget, `QA_DESIGN_TARGETS`, said in the results.
2. **Cases before code.** The model lists each case — what it checks and what should
   happen — then writes the file, in the codebase's framework, importing the code the
   way its own tests do, with everything outside the process replaced by fakes.
3. **It runs where the codebase's tests ran**: the same container image and install,
   no network.
4. **A failure is judged by a second call**: the code's fault (a finding, *likely*, with
   the failing output) or the test's (corrected and run again, twice at most). When
   unsure it is the test's. A suspected finding a test reproduces becomes *likely*.

Every test is kept, passing or not, to be read and added to the codebase's own.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import structlog

from codelith.apps.qa import sandbox
from codelith.apps.qa.checks.review import _json, numbered
from codelith.apps.qa.checks.review import _targets as risky
from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding
from codelith.apps.qa.routes import chain_of, route_access
from codelith.config import get_settings
from codelith.core.cancellation import JobCancelled
from codelith.knowledge.guide import GuideService
from codelith.languages import registry

logger = structlog.get_logger(__name__)

RULES = {"tests.designed-fails": "Fails a test designed for it"}
RUNTIME_LANGUAGES = {"Python": {"python"}, "Node.js": {"typescript", "javascript"}, "Go": {"go"}}
#: Seconds one designed test file may run.
TIMEOUT = 300
#: Corrections of a test judged wrong, after the first try.
FIXES = 2
_SEVERITIES = ("high", "medium", "low")
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_MAX_FILE_LINES = 300


@dataclass(slots=True)
class Target:
    path: str
    name: str
    start: int
    end: int
    #: `untested` or `finding`.
    reason: str
    finding: Finding | None = None


@dataclass(slots=True)
class Designed:
    target: Target
    runtime: str
    framework: str
    file_path: str
    code: str = ""
    cases: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    #: `passed`, `bug`, `wrong`, `did-not-run`.
    outcome: str = "did-not-run"
    tries: int = 0
    verdict: str = ""
    output: str = ""
    finding: Finding | None = None


def framework_for(plan: sandbox.Plan, declared: set[str]) -> str | None:
    if plan.runtime == "Python":
        return "pytest"
    if plan.runtime == "Go":
        return "go test"
    if plan.runtime == "Node.js":
        for name in ("vitest", "jest"):
            if name in declared or name in plan.test:
                return name
    return None


def _fits(plan: sandbox.Plan, path: str) -> bool:
    provider = registry.for_path(path)
    return (
        provider is not None
        and provider.language in RUNTIME_LANGUAGES.get(plan.runtime, set())
        and not provider.is_test_file(path)
        and (not plan.folder or path.startswith(plan.folder + "/"))
    )


async def targets(ctx: RunContext, plan: sandbox.Plan, budget: int) -> list[Target]:
    """Suspected findings worth reproducing first, then the riskiest code no test reaches."""
    ra = await route_access(ctx)
    out: list[Target] = []
    taken: set[tuple[str, str]] = set()

    def span(path: str, line: int) -> tuple[str, int, int] | None:
        best = None
        for qname, start, end in ra.symbols.get(path, []):
            if start <= line <= end and (best is None or start >= best[1]):
                best = (qname, start, end)
        return best

    suspected = sorted(
        (
            f for f in ctx.cache.get("found", [])
            if f.confidence in ("suspected", "likely") and f.source in ("model", "rule")
            and f.area in ("breaks", "errors", "security") and f.path and f.line and _fits(plan, f.path)
        ),
        key=lambda f: (_SEVERITY_RANK.get(f.severity, 9), f.path or "", f.line or 0),
    )
    for f in suspected:
        found = span(f.path, f.line)
        if found is None or (f.path, found[0]) in taken:
            continue
        out.append(Target(f.path, found[0], found[1], found[2], "finding", f))
        taken.add((f.path, found[0]))
        if len(out) >= min(2, budget):
            break

    for _score, path, qname, start, end in await risky(ctx, budget=budget * 4, keep=lambda p: _fits(plan, p), untested_only=True):
        if len(out) >= budget:
            break
        if (path, qname) in taken or qname.rsplit(".", 1)[-1].startswith("_"):
            continue
        out.append(Target(path, qname, start, end, "untested"))
        taken.add((path, qname))
    return out


def _module(plan: sandbox.Plan, path: str) -> str:
    rel = path[len(plan.folder) + 1 :] if plan.folder else path
    if rel.startswith("src/"):
        rel = rel[4:]
    parts = list(PurePosixPath(rel).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def placement(ctx: RunContext, plan: sandbox.Plan, framework: str, target: Target, n: int, text: str) -> tuple[str, str]:
    """`(where the test file goes, how it imports the code)`, relative to the codebase's root."""
    p = PurePosixPath(target.path)
    if plan.runtime == "Python":
        tests = [
            PurePosixPath(f.path[len(plan.folder) + 1 :] if plan.folder else f.path).parts[0]
            for f in ctx.all_files
            if f.path.endswith(".py") and _in(plan, f.path) and (pr := registry.for_path(f.path)) and pr.is_test_file(f.path)
        ]
        folder = Counter(t for t in tests if not t.endswith(".py")).most_common(1)
        where = f"{folder[0][0] if folder else 'tests'}/test_codelith_qa_{n}.py"
        module, top = _module(plan, target.path), target.name.split(".")[0]
        hint = (
            f"Import what you test from `{module}` — `from {module} import {top}` — the tests run from the "
            "project's root folder, which is on the import path."
        )
    elif plan.runtime == "Go":
        package = re.search(r"^package\s+(\w+)", text, re.M)
        where = str(p.parent / f"codelith_qa_{n}_test.go")
        hint = (
            f"The file sits in the same folder as the code, in `package {package.group(1) if package else 'main'}`: "
            f"call `{target.name.split('.')[-1]}` directly. Name every test `TestCodelithQA...`."
        )
    else:
        ext = ".tsx" if p.suffix == ".tsx" else ".ts" if p.suffix == ".ts" else ".js"
        where = str(p.parent / f"{p.stem}.codelith-qa-{n}.test{ext}")
        hint = (
            f"The file sits next to the code: import from `./{p.stem}` the way the code's own modules import "
            f"each other, and import the test functions from `{framework}`."
        )
    if plan.folder and plan.runtime == "Python":
        where = f"{plan.folder}/{where}"
    return where, hint


def _in(plan: sandbox.Plan, path: str) -> bool:
    return not plan.folder or path.startswith(plan.folder + "/")


def _command(plan: sandbox.Plan, framework: str, rel: str, n: int, code: str) -> str:
    report = f"/work/{sandbox.OUT}/designed-{n}"
    if plan.runtime == "Python":
        return f"python -m pytest -q -p no:cacheprovider -o junit_family=xunit1 --junitxml={report}.xml {rel}"
    if plan.runtime == "Go":
        names = re.findall(r"^func (Test\w+)\(", code, re.M) or ["TestCodelithQA"]
        folder = str(PurePosixPath(rel).parent)
        return f"go test -json -count=1 -run '^({'|'.join(names)})$' ./{'' if folder == '.' else folder}"
    if framework == "vitest":
        return f"npx --no-install vitest run {rel} --reporter=junit --outputFile={report}.xml"
    return f"npx --no-install jest {rel} --ci --json --outputFile={report}.json"


def _cases(copy: Path, plan: sandbox.Plan, framework: str, n: int, ran: sandbox.Ran) -> list[sandbox.TestCase]:
    out = copy / sandbox.OUT
    if plan.runtime == "Go":
        return sandbox.parse_go(ran.output)
    if framework == "jest":
        report = out / f"designed-{n}.json"
        return sandbox.parse_jest(report.read_text(encoding="utf-8", errors="replace")) if report.is_file() else []
    report = out / f"designed-{n}.xml"
    return sandbox.parse_junit(report.read_text(encoding="utf-8", errors="replace")) if report.is_file() else []


def _excerpt(lines: list[str], start: int, end: int) -> str:
    if len(lines) <= _MAX_FILE_LINES:
        return numbered(lines, 1, len(lines))
    head = numbered(lines, 1, 40)
    return head + "\n  ...\n" + numbered(lines, max(41, start - 20), min(len(lines), end + 5))


def _code_of(reply: dict | None) -> str:
    code = str((reply or {}).get("code") or "").strip()
    if code.startswith("```"):
        code = code.split("\n", 1)[1] if "\n" in code else ""
        code = code.rsplit("```", 1)[0]
    return code.strip() + "\n" if code.strip() else ""


async def _style(ctx: RunContext, plan: sandbox.Plan) -> str:
    """The house style: where tests live and how they are named, and the start of one of them."""
    parts: list[str] = []
    recipe = await GuideService(ctx.db, ctx.kb).recipe("test")
    if recipe is not None:
        parts.append("How this codebase's tests are laid out: " + " ".join(recipe.lines))
    example = next(
        (
            f for f in ctx.all_files
            if f.kind is None and _in(plan, f.path) and (pr := registry.for_path(f.path)) is not None
            and pr.language in RUNTIME_LANGUAGES[plan.runtime] and pr.is_test_file(f.path) and 6 < f.lines < 400
        ),
        None,
    )
    if example is not None:
        head = "\n".join((await ctx.text(example)).splitlines()[:50])
        parts.append(f"Follow the style of its existing tests, such as the start of {example.path}:\n{head}")
    return "\n\n".join(parts)


async def design(
    ctx: RunContext, runner: sandbox.Runner, copy: Path, plan: sandbox.Plan, declared: set[str], tag: str
) -> list[Finding]:
    """Write, run and judge tests for this runtime's riskiest untested code. Returns new findings."""
    from codelith.llm import client as llm
    from codelith.llm.prompts.test_design_prompts import TEST_DESIGN, TEST_VERDICT
    from codelith.llm.router import select_spec

    framework = framework_for(plan, declared)
    budget = get_settings().QA_DESIGN_TARGETS
    if framework is None:
        ctx.notes.append(f"No tests were designed for {plan.runtime}: no test framework this can drive was found (vitest or jest).")
        return []
    if budget <= 0:
        return []
    chosen = await targets(ctx, plan, budget)
    if not chosen:
        ctx.notes.append(f"No {plan.runtime} function in scope needed a designed test: the risky ones are tested already.")
        return []

    ra = await route_access(ctx)
    style = await _style(ctx, plan)
    spec = select_spec("write")
    language = {"Python": "Python", "Go": "Go", "Node.js": "TypeScript or JavaScript"}[plan.runtime]
    packages = ", ".join(sorted(declared)) or "none"
    kept: list[Designed] = ctx.cache.setdefault("designed", [])
    out: list[Finding] = []
    calls = 0

    async def ask(messages: list[dict]) -> dict | None:
        nonlocal calls
        calls += 1
        return _json(await llm.chat_completion(messages, spec=spec))

    try:
        for n, target in enumerate(chosen, 1):
            await ctx.checkpoint()
            text = "\n".join(await ctx.lines(target.path))
            lines = text.splitlines()
            file_path, hint = placement(ctx, plan, framework, target, n, text)
            d = Designed(target, plan.runtime, framework, file_path)
            kept.append(d)
            context = []
            routes = ra.reaching(target.path, target.start, target.name)
            if routes:
                context.append(f"Reached from {', '.join(r.name for r in routes[:3])}: {' -> '.join(chain_of(routes[0], target.path, target.name))}.")
            focus = "Nothing tests this function yet."
            if target.finding is not None:
                f = target.finding
                focus = (
                    f"A reviewer suspects a problem at line {f.line}: {f.title}. {f.message[:400]} "
                    "Include at least one test that fails if the problem is real and passes once it is fixed."
                )
            reply = await ask(
                TEST_DESIGN.render(
                    language=language,
                    framework=framework,
                    packages=packages,
                    test_path=file_path,
                    import_hint=hint,
                    focus=focus,
                    style=style,
                    function=target.name,
                    path=target.path,
                    start=str(target.start),
                    end=str(target.end),
                    context="\n".join(context),
                    code=_excerpt(lines, target.start, target.end),
                )
            )
            code = _code_of(reply)
            d.cases = [
                {k: str(c.get(k) or "")[:300] for k in ("name", "checks", "expect")}
                for c in (reply or {}).get("cases") or [] if isinstance(c, dict)
            ][:12]
            if not code:
                d.verdict = "The model wrote no test."
                continue
            dest = copy / file_path
            rel = file_path[len(plan.folder) + 1 :] if plan.folder else file_path
            try:
                for attempt in range(1 + FIXES):
                    d.code, d.tries = code, attempt + 1
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(code, encoding="utf-8")
                    ran = await sandbox.run_offline(
                        runner, copy, plan, _command(plan, framework, rel, n, code), ctx.token,
                        f"codelith-qa-{tag}-designed-{n}", TIMEOUT,
                    )
                    cases = _cases(copy, plan, framework, n, ran)
                    d.results = [{"name": c.name.split("::")[-1], "outcome": c.outcome, "message": c.message[:800]} for c in cases]
                    d.output = "\n".join(ran.output.strip().splitlines()[-60:])
                    failing = [c for c in cases if c.outcome in ("failed", "error")]
                    if cases and not failing and ran.exit_code == 0:
                        d.outcome, d.verdict = "passed", ""
                        break
                    if ran.timed_out:
                        d.outcome, d.verdict = "wrong", "It ran out of time."
                        break
                    printed = "\n\n".join(f"{c.name}:\n{c.message}" for c in failing)[:5000] or d.output[-5000:]
                    verdict = await ask(
                        TEST_VERDICT.render(
                            function=target.name,
                            path=target.path,
                            code=numbered(lines, target.start, target.end),
                            test_path=file_path,
                            test=code,
                            output=printed,
                        )
                    ) or {}
                    d.verdict = str(verdict.get("why") or "").strip()[:800]
                    if verdict.get("verdict") == "bug" and failing:
                        d.outcome = "bug"
                        d.finding = _judged_bug(target, d, verdict, failing, printed)
                        if target.finding is None:
                            out.append(d.finding)
                        break
                    fixed = _code_of(verdict)
                    if attempt == FIXES or not fixed:
                        d.outcome = "wrong"
                        break
                    code = fixed
            finally:
                dest.unlink(missing_ok=True)
    except JobCancelled:
        raise
    except Exception as exc:  # the model is a guest: when it fails, the rest of the run still stands
        logger.warning("qa_design_failed", error=f"{type(exc).__name__}: {exc}")
        ctx.notes.append(f"The model could not be reached ({type(exc).__name__}): test design stopped after {calls} call(s).")

    mine = [d for d in kept if d.runtime == plan.runtime]
    counts = Counter(d.outcome for d in mine)
    ctx.notes.append(
        f"The model designed tests for {len(mine)} {plan.runtime} function(s) in {calls} call(s): "
        f"{counts['passed']} passed, {counts['bug']} found a bug, {counts['wrong']} given up on as wrong tests"
        + (f", {counts['did-not-run']} not written" if counts["did-not-run"] else "")
        + ". Each is kept with the run, to read and add to the codebase's own tests."
    )
    return out


def _judged_bug(target: Target, d: Designed, verdict: dict, failing: list[sandbox.TestCase], printed: str) -> Finding:
    names = [c.name.split("::")[-1] for c in failing]
    if target.finding is not None:
        f = target.finding
        f.confidence = "likely"
        f.evidence["reproduced_by"] = d.file_path
        f.evidence["designed_tests"] = names
        f.message += f"\n\nA test designed to reproduce it fails ({', '.join(f'`{n}`' for n in names[:3])}): {d.verdict}"
        return f
    try:
        line = int(verdict.get("line"))
    except (TypeError, ValueError):
        line = target.start
    if not target.start <= line <= target.end:
        line = target.start
    severity = str(verdict.get("severity") or "medium").lower()
    return Finding(
        rule="tests.designed-fails",
        area="breaks",
        severity=severity if severity in _SEVERITIES else "medium",
        title=f"`{target.name}` fails a test designed for it",
        message=(
            f"{d.verdict}\n\nThe model wrote the expectation and a second look judged the code at fault, so read "
            f"the test before trusting it. What failed:\n\n{printed[:1500]}"
        ),
        fix=str(verdict.get("fix") or "").strip()[:500] or "Make the code do what the test expects, or say why it should not.",
        path=target.path,
        line=line,
        confidence="likely",
        source="test",
        evidence={"designed_test": d.file_path, "designed_tests": names},
    )


def as_rows(kept: list[Designed]) -> list[dict]:
    """What the service stores for each designed test, once fingerprints are known."""
    return [
        {
            "target_path": d.target.path,
            "target_name": d.target.name,
            "target_line": d.target.start,
            "reason": d.target.reason,
            "runtime": d.runtime,
            "framework": d.framework,
            "file_path": d.file_path,
            "code": d.code,
            "cases_json": d.cases,
            "results_json": d.results,
            "outcome": d.outcome,
            "tries": d.tries,
            "verdict": d.verdict,
            "output": d.output[-8000:],
            "finding_fingerprint": d.finding.fingerprint if d.finding is not None else None,
        }
        for d in kept
    ]


__all__ = ["RULES", "Designed", "Target", "as_rows", "design", "framework_for", "placement", "targets"]
