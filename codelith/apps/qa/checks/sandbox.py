"""
Run tests: the codebase installed and tested in throwaway containers, and its own tools
run there too (`apps/qa/sandbox.py`).

What it can say that nothing else here can is **confirmed**: the install failed on a
clean machine, this test fails, this name is undefined according to the type checker.
Each finding carries the output that proves it.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path, PurePosixPath

import structlog

from codelith.apps.qa import sandbox
from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding
from codelith.ingestion.scratch import scratch_root
from codelith.knowledge.runbook import RunbookService
from codelith.languages import registry

logger = structlog.get_logger(__name__)

#: It runs when either is asked; what the tools find in other areas is kept only when that area is.
AREAS = frozenset({"tests", "breaks"})
TITLE = "The install, the tests and the tools, run in throwaway containers"
RULES = {
    "breaks.install-fails": "A clean install fails",
    "breaks.tests-did-not-run": "Tests that could not run",
    "tests.failing": "Tests that fail",
    "tool.ruff": "Found by ruff",
    "tool.mypy": "Type errors (mypy)",
    "tool.go-vet": "Found by go vet",
    "tool.tsc": "Type errors (TypeScript)",
}

_RUNTIME_LANGUAGES = {"Python": {"python"}, "Node.js": {"typescript", "javascript"}, "Go": {"go"}}
#: ruff rule prefixes worth a finding, and where they go. Style rules are not QA's.
_RUFF = (
    (re.compile(r"^(F821|F822|F823|F811|F632|F401|E999|PLE)"), "breaks", "medium"),
    (re.compile(r"^(B|BLE|TRY|ASYNC)"), "errors", "low"),
    (re.compile(r"^S"), "security", "medium"),
)
_MYPY = re.compile(r"^(?P<path>[^:\n]+):(?P<line>\d+):(?:\d+:)?\s*error:\s*(?P<msg>.*?)(?:\s+\[(?P<code>[\w-]+)\])?$")
_GO_VET = re.compile(r"^(?:\./)?(?P<path>[^:\s]+\.go):(?P<line>\d+):(?:\d+:)?\s*(?P<msg>.+)$")
_TSC = re.compile(r"^(?P<path>[^(\n]+)\((?P<line>\d+),\d+\):\s*error\s+(?P<code>TS\d+):\s*(?P<msg>.+)$")
_MAX_PER_TOOL = 60
#: mypy codes about the environment, not the code: a missing stub is not a bug.
_MYPY_SKIP = frozenset({"import-untyped", "import-not-found", "import"})


async def _copy(ctx: RunContext) -> Path:
    """A fresh copy of the reading's exact commit: from git when there is one, else its kept files."""
    from codelith.services.snapshot_service import _materialise

    dest = scratch_root() / str(uuid.uuid4())
    dest.parent.mkdir(parents=True, exist_ok=True)
    source = next((s for s in ctx.sources if s.source_type in ("github", "gitlab", "bitbucket", "local")), None)
    if source is not None and ctx.kb.commit_sha:
        import asyncio

        why = await asyncio.to_thread(_materialise, source, ctx.kb.commit_sha, dest)
        if why is None:
            return dest
        logger.info("qa_sandbox_copy_from_kept_files", reason=why)
    dest.mkdir(parents=True, exist_ok=True)
    for f in ctx.all_files:
        if f.masked:
            continue  # a real .env never goes in, masked or not
        target = dest / f.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(await ctx.text(f), encoding="utf-8")
    ctx.notes.append("The tests ran on the files the reading kept (no git source): files it did not keep, such as images, were missing.")
    return dest


def _tail(text: str, lines: int = 25) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


async def run(ctx: RunContext) -> list[Finding]:
    from codelith.apps.qa import designed  # it imports the review check: not at import time

    runner = ctx.cache.get("sandbox_runner") or sandbox.Runner()
    why = await sandbox.docker_ready(runner)
    if why:
        ctx.notes.append(f"{why} The tests and tools were not run.")
        return []

    book = await RunbookService(ctx.db, ctx.kb).build()
    declared: dict[str, set[str]] = {}
    for f in ctx.all_files:
        if f.kind == "manifest":
            for provider in registry.manifest_providers(f.path):
                runtime = {"PyPI": "Python", "npm": "Node.js", "Go": "Go"}.get(provider.ecosystem or "")
                if runtime:
                    declared.setdefault(runtime, set()).update(d.name.lower() for d in provider.declared(f.path, await ctx.text(f)))
    has_tests: dict[str, bool] = {}
    for f in ctx.all_files:
        provider = registry.for_path(f.path) if f.kind is None else None
        if provider is not None and provider.is_test_file(f.path):
            for runtime, languages in _RUNTIME_LANGUAGES.items():
                if provider.language in languages:
                    has_tests[runtime] = True
    plans = sandbox.plans(book, declared, has_tests)
    if not plans:
        ctx.notes.append("No test command and test files were found together for any runtime: there was nothing to run.")
        return []

    out: list[Finding] = []
    copy = await _copy(ctx)
    try:
        for plan in plans:
            await ctx.checkpoint()
            tag = uuid.uuid4().hex[:8]
            result = await sandbox.run_plan(runner, copy, plan, ctx.token, tag)
            out += _findings(ctx, result)
            if result.installed:
                out += await designed.design(ctx, runner, copy, plan, declared.get(plan.runtime, set()), tag)
                await _verify_fixes(ctx, runner, copy, plan, result, tag)
    finally:
        sandbox.remove(copy)
    return out


_FAILED = ("failed", "error")


async def _verify_fixes(
    ctx: RunContext, runner: sandbox.Runner, copy: Path, plan: sandbox.Plan, result: sandbox.SandboxResult, tag: str
) -> None:
    """
    Apply every suggested patch in this runtime's folder to the copy, run its tests
    again, and say on each patch whether any test newly failed. All at once, so one
    more run whatever their number; when one breaks something, none is marked.
    """
    from codelith.apps.qa import fixes

    if not result.cases or plan.report == "exit":
        return
    found = ctx.cache.get("found", [])
    await fixes.attach(ctx, found)
    in_folder = [f for f in found if f.patch and f.path and (not plan.folder or f.path.startswith(plan.folder + "/"))]
    if not in_folder:
        return
    saved: dict[str, str] = {}
    applied: list[Finding] = []
    for f in in_folder:
        if f.path in saved:
            continue  # two patches to one file would need each other's line numbers
        before = fixes.apply_to(copy, f)
        if before is not None:
            saved[f.path] = before
            applied.append(f)
    if not applied:
        return
    try:
        ran = await sandbox.run_offline(runner, copy, plan, plan.test, ctx.token, f"codelith-qa-{tag}-verify")
        if plan.report == "junit":
            junit = copy / sandbox.OUT / "junit.xml"
            after = sandbox.parse_junit(junit.read_text(encoding="utf-8", errors="replace"), plan.folder) if junit.is_file() else []
        else:
            after = sandbox.parse_go(ran.output, plan.folder)
    finally:
        for path, text in saved.items():
            (copy / path).write_text(text, encoding="utf-8")
    failed_before = {c.name for c in result.cases if c.outcome in _FAILED}
    newly = sorted({c.name for c in after if c.outcome in _FAILED} - failed_before)
    if not after:
        ctx.notes.append("The tests did not run again with the suggested fixes applied, so the fixes are not checked.")
    elif newly:
        ctx.notes.append(
            f"With the {len(applied)} suggested fix(es) applied, {len(newly)} test(s) newly failed "
            f"({', '.join(n.split('::')[-1] for n in newly[:3])}): the fixes are not marked as checked."
        )
    else:
        for f in applied:
            f.evidence["verified"] = (
                f"With this change{' and ' + str(len(applied) - 1) + ' other suggested fix(es)' if len(applied) > 1 else ''} "
                f"applied, the {len(after)} {plan.runtime} tests ran again in the sandbox and none newly failed."
            )
        ctx.notes.append(f"{len(applied)} suggested fix(es) were applied in the sandbox and the tests ran again: none newly failed.")


def _manifest_for(ctx: RunContext, plan: sandbox.Plan) -> str | None:
    for f in ctx.all_files:
        if f.kind == "manifest" and str(PurePosixPath(f.path).parent) in (plan.folder or ".", plan.folder):
            provider = next(iter(registry.manifest_providers(f.path)), None)
            runtime = {"PyPI": "Python", "npm": "Node.js", "Go": "Go"}.get(getattr(provider, "ecosystem", "") or "")
            if runtime == plan.runtime:
                return f.path
    return None


def _findings(ctx: RunContext, result: sandbox.SandboxResult) -> list[Finding]:
    plan = result.plan
    out: list[Finding] = []
    install = result.install
    if not result.installed and install is not None:
        out.append(
            Finding(
                rule="breaks.install-fails",
                area="breaks",
                severity="high",
                title=f"A clean {plan.runtime} install fails",
                message=(
                    f"In a fresh `{plan.image}` container the install "
                    + ("ran out of time" if install.timed_out else f"stopped with exit code {install.exit_code}")
                    + ": anyone setting this up from scratch hits the same wall. The end of its output:\n\n"
                    + _tail(install.output)
                ),
                fix="Make a clean install work: declare what is missing, pin what broke, and keep the install command "
                "in the README the one that works.",
                path=_manifest_for(ctx, plan),
                line=None,
                source="test",
                evidence={"command": " && ".join(plan.install), "image": plan.image},
            )
        )
        ctx.notes.append(f"The {plan.runtime} install failed in `{plan.image}`, so its tests and tools did not run.")
        return out

    if result.test is not None:
        cases = result.cases
        counts = {k: sum(1 for c in cases if c.outcome == k) for k in ("passed", "failed", "error", "skipped")}
        if cases:
            ctx.notes.append(
                f"Ran {len(cases)} {plan.runtime} tests in a clean `{plan.image}` container with no network: "
                f"{counts['passed']} passed, {counts['failed'] + counts['error']} failed, {counts['skipped']} skipped "
                f"({result.test.seconds:.0f}s)."
            )
        elif result.test.exit_code not in (0, 5) or result.test.timed_out:
            out.append(
                Finding(
                    rule="breaks.tests-did-not-run",
                    area="breaks",
                    severity="medium",
                    title=f"The {plan.runtime} tests did not run",
                    message=("They ran out of time. " if result.test.timed_out else f"`{plan.test}` stopped with exit code "
                             f"{result.test.exit_code} before reporting any test. ") + "The end of its output:\n\n" + _tail(result.test.output),
                    fix="Run the test command on a clean checkout and fix what stops it collecting the tests.",
                    path=_manifest_for(ctx, plan),
                    source="test",
                )
            )
        elif result.test.exit_code == 0:
            ctx.notes.append(f"The {plan.runtime} tests passed in a clean `{plan.image}` container ({result.test.seconds:.0f}s).")
        failing = [c for c in cases if c.outcome in ("failed", "error")]
        for case in failing[:50]:
            out.append(
                Finding(
                    rule="tests.failing",
                    area="tests",
                    severity="medium",
                    title=f"`{case.name.split('::')[-1]}` fails",
                    message="It fails on a clean install with no network: either the code it tests is broken, or the test "
                    "depends on something outside it (a service, a file, the network, the clock). Its output:\n\n" + case.message[:1500],
                    fix="Run it alone, read the assertion, and fix the code or the test's assumption.",
                    path=case.file,
                    line=case.line,
                    source="test",
                    evidence={"test": case.name, "outcome": case.outcome},
                )
            )
        if len(failing) > 50:
            ctx.notes.append(f"{len(failing) - 50} more failing tests were not listed one by one.")

    in_scope = {f.path for f in ctx.files}
    for tool, ran in result.tools.items():
        out += [
            f for f in _tool_findings(tool, ran, plan.folder)
            if ctx.wants(f.area) and f.path in in_scope
        ]
    return out


def _rel(path: str, folder: str) -> str:
    path = path.replace("\\", "/")
    for prefix in ("/work/", "./"):
        if path.startswith(prefix):
            path = path[len(prefix):]
    if folder and not path.startswith(folder + "/"):
        path = f"{folder}/{path}"
    return path


def _tool_findings(tool: str, ran: sandbox.Ran, folder: str) -> list[Finding]:
    out: list[Finding] = []
    if tool == "ruff":
        start = ran.output.find("[")
        try:
            items = json.loads(ran.output[start:]) if start >= 0 else []
        except ValueError:
            items = []
        for item in items:
            code = str(item.get("code") or "")
            for pattern, area, severity in _RUFF:
                if pattern.match(code):
                    out.append(
                        Finding(
                            rule="tool.ruff",
                            area=area,
                            severity="high" if code in ("F821", "E999") else severity,
                            title=f"ruff {code}: {item.get('message', '')}",
                            message=f"ruff reports {code} here, in a clean install: {item.get('message', '')}.",
                            fix=(item.get("fix") or {}).get("message") or "Fix what ruff reports, or say in a `# noqa` why not.",
                            path=_rel(str(item.get("filename", "")), folder),
                            line=(item.get("location") or {}).get("row"),
                            source="tool",
                            evidence={"code": code},
                        )
                    )
                    break
            if len(out) >= _MAX_PER_TOOL:
                break
    else:
        pattern = {"mypy": _MYPY, "go vet": _GO_VET, "tsc": _TSC}[tool]
        for raw in ran.output.splitlines():
            m = pattern.match(raw.strip())
            if not m:
                continue
            code = m.groupdict().get("code") or ""
            if code in _MYPY_SKIP:
                continue
            serious = code in ("name-defined", "attr-defined", "call-arg", "arg-type", "return-value", "TS2304", "TS2339", "TS2345") or tool == "go vet"
            out.append(
                Finding(
                    rule=f"tool.{tool.replace(' ', '-')}",
                    area="breaks" if tool != "go vet" else "errors",
                    severity="medium" if serious else "low",
                    title=f"{tool}{' ' + code if code else ''}: {m.group('msg')[:160]}",
                    message=f"{tool} reports this in a clean install: {m.group('msg')}",
                    fix=f"Fix what {tool} reports.",
                    path=_rel(m.group("path"), folder),
                    line=int(m.group("line")),
                    source="tool",
                    evidence={"code": code},
                )
            )
            if len(out) >= _MAX_PER_TOOL:
                break
    return out


__all__ = ["AREAS", "RULES", "TITLE", "run"]
