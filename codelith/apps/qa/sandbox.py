"""
Running a codebase's own install, tests and tools in a throwaway container.

**Two containers, never one.** The first installs the dependencies and is the only one
with a network: packages have to come from somewhere. The second runs the tests and the
tools with no network at all, as a non-root user, on a read-only root with a scratch
`/tmp`, with memory, CPU and process limits and a time limit. Neither is given any of
this machine's environment, so no key of yours is ever inside. Both work on a fresh
copy of the reading's exact commit in a scratch folder, removed afterwards.

How to install and test comes from the runbook (`knowledge/runbook.py`): the same
commands a person would type, minus the ones that need a tool the image lacks (`make`).
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from codelith.core.cancellation import CancellationToken

logger = structlog.get_logger(__name__)

#: Seconds each container may take.
INSTALL_TIMEOUT = 900
TEST_TIMEOUT = 1200
#: What a container may use.
LIMITS = ["--memory", "3g", "--cpus", "2", "--pids-limit", "1024"]
#: Where results are written inside the copy, read back after.
OUT = ".codelith-qa"
#: Kept of each log, from the end, where errors are.
LOG_TAIL = 12_000


@dataclass(slots=True)
class Plan:
    """How to install and test one runtime's part of the code, in a container."""

    runtime: str
    image: str
    #: The folder (relative to the copy's root) the commands run in.
    folder: str
    install: list[str]
    test: str
    #: How the test command reports: `junit` (a file), `gojson` (`go test -json`), `exit`.
    report: str
    tools: list[tuple[str, str]] = field(default_factory=list)  # (tool, command)
    #: Set in both containers. Caches the second one needs live under the copy, since
    #: each container is thrown away and the second has no network to fetch again.
    env: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Ran:
    """What one container did."""

    exit_code: int | None
    output: str
    seconds: float
    timed_out: bool = False


@dataclass(slots=True)
class TestCase:
    name: str
    file: str | None
    line: int | None
    #: `passed`, `failed`, `error`, `skipped`.
    outcome: str
    message: str = ""


@dataclass(slots=True)
class SandboxResult:
    plan: Plan
    installed: bool
    install: Ran | None = None
    test: Ran | None = None
    cases: list[TestCase] = field(default_factory=list)
    tools: dict[str, Ran] = field(default_factory=dict)


class Runner:
    """
    Runs `docker` with arguments. A stand-in replaces it in tests.

    A plain process polled from the loop, not an asyncio subprocess: the worker's loop
    is not guaranteed to support those on Windows. Stopping it removes the container
    by name too, because killing the `docker` client leaves the container running.
    """

    async def __call__(self, args: list[str], timeout: float, token: CancellationToken | None) -> Ran:
        start = time.monotonic()
        name = args[args.index("--name") + 1] if "--name" in args else None
        with tempfile.TemporaryFile() as out:
            try:
                proc = subprocess.Popen(
                    ["docker", *args],
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except FileNotFoundError:
                return Ran(None, "docker is not installed", 0.0)
            timed_out = False
            try:
                while proc.poll() is None:
                    await asyncio.sleep(0.5)
                    if token is not None:
                        await token.raise_if_cancelled()
                    if time.monotonic() - start > timeout:
                        timed_out = True
                        await asyncio.to_thread(_stop, proc, name)
                        break
            except BaseException:
                await asyncio.shield(asyncio.to_thread(_stop, proc, name))
                raise
            size = out.seek(0, 2)
            out.seek(max(0, size - LOG_TAIL * 4))
            text = out.read().decode("utf-8", "replace")
        return Ran(proc.returncode, text[-LOG_TAIL:], time.monotonic() - start, timed_out)


def _stop(proc: subprocess.Popen, name: str | None) -> None:
    if name:
        try:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("qa_sandbox_container_not_removed", name=name)
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


async def docker_ready(runner: Runner) -> str | None:
    """`None` when Docker answers; otherwise why it does not, in a sentence."""
    from codelith.core.runtime import in_container

    if in_container():
        # The copy lives in this container's filesystem, which the host's Docker cannot
        # mount; handing this container the host's socket would also hand it the host.
        return (
            "Codelith is running inside its own container, where it cannot start others: "
            "Run tests needs Codelith run from source on a machine with Docker."
        )
    ran = await runner(["info", "--format", "{{.ServerVersion}}"], 20, None)
    if ran.exit_code == 0 and ran.output.strip():
        return None
    if "not installed" in ran.output:
        return "Docker is not installed on this machine."
    return "Docker is installed but not running: start Docker Desktop (or the Docker service) and run the tests again."


def _version(spec: str | None, default: str) -> str:
    m = re.search(r"(\d+)(?:\.(\d+))?", spec or "")
    if not m:
        return default
    return f"{m.group(1)}.{m.group(2)}" if m.group(2) else m.group(1)


def plans(book, declared_dev: dict[str, set[str]], has_tests: dict[str, bool]) -> list[Plan]:
    """
    One plan per runtime that has something to test. `book` is the runbook;
    `declared_dev` the dev packages per runtime (to know which tools are configured);
    `has_tests` whether test files exist for each runtime.
    """
    out: list[Plan] = []
    needs = {n.what: n for n in book.needs if n.kind == "runtime"}
    installs = [s for s in book.install if not s.command.split(" && ")[-1].startswith(("make ", "just "))]
    tests = [s for s in book.test if not s.command.split(" && ")[-1].startswith(("make ", "just "))]

    def folder_of(command: str) -> str:
        return command.split(" && ", 1)[0][3:] if command.startswith("cd ") else ""

    def strip(command: str) -> str:
        return command.split(" && ", 1)[1] if command.startswith("cd ") else command

    if "Python" in needs and has_tests.get("Python"):
        version = _version(needs["Python"].version, "3.12")
        python_steps = [s for s in installs if re.match(r"^(cd \S+ && )?(pip|uv|poetry) ", s.command)]
        pip = [strip(s.command) for s in python_steps]
        install = ["python -m venv /work/.venv", ". /work/.venv/bin/activate", "pip install -q --upgrade pip"]
        for cmd in pip or ["pip install -q -e ."]:
            cmd = cmd.replace("uv sync", "pip install -q -e .").replace("poetry install", "pip install -q -e .")
            install.append(cmd if " -q" in cmd else cmd.replace("pip install", "pip install -q", 1))
        dev = declared_dev.get("Python", set())
        extra = [t for t in ("pytest", "ruff", "mypy") if t == "pytest" or t in dev]
        install.append("pip install -q " + " ".join(extra))
        tools = []
        if "ruff" in dev:
            tools.append(("ruff", "ruff check --output-format json --exit-zero ."))
        if "mypy" in dev:
            tools.append(("mypy", "mypy --hide-error-context --no-error-summary --show-column-numbers . || true"))
        out.append(
            Plan(
                runtime="Python",
                image=f"python:{version}-slim",
                folder=folder_of(python_steps[0].command) if python_steps else "",
                install=install,
                test=f"python -m pytest -q -p no:cacheprovider -o junit_family=xunit1 --junitxml=/work/{OUT}/junit.xml",
                report="junit",
                tools=tools,
                env={"PIP_NO_CACHE_DIR": "1"},
            )
        )
    if "Node.js" in needs and has_tests.get("Node.js"):
        node_test = next((s for s in tests if re.search(r"\b(npm|pnpm|yarn|bun) test\b", s.command)), None)
        node_install = next((s for s in installs if re.search(r"\b(npm|pnpm|yarn|bun) (ci|install)\b", s.command)), None)
        if node_test is not None:
            folder = folder_of(node_test.command)
            install_cmd = strip(node_install.command) if node_install else "npm install"
            pm = install_cmd.split(" ", 1)[0]
            via = "corepack " if pm in ("pnpm", "yarn") else ""
            test_cmd = strip(node_test.command)
            tools = [("tsc", "npx --no-install tsc --noEmit --pretty false || true")] if "typescript" in declared_dev.get("Node.js", set()) else []
            out.append(
                Plan(
                    runtime="Node.js",
                    image=f"node:{_version(needs['Node.js'].version, '20').split('.')[0]}-slim",
                    folder=folder,
                    install=[via + install_cmd],
                    test=via + test_cmd if test_cmd.startswith(("pnpm ", "yarn ")) else test_cmd,
                    report="exit",
                    tools=tools,
                    env={"COREPACK_HOME": f"/work/{OUT}/corepack", "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0"},
                )
            )
    if "Go" in needs and has_tests.get("Go"):
        out.append(
            Plan(
                runtime="Go",
                image=f"golang:{_version(needs['Go'].version, '1.22')}",
                folder="",
                install=["go mod download"],
                test="go test -json ./...",
                report="gojson",
                tools=[("go vet", "go vet ./... 2>&1 || true")],
                env={"GOMODCACHE": f"/work/{OUT}/gomod", "GOCACHE": "/tmp/gocache", "GOPATH": "/tmp/go",
                     "GOTOOLCHAIN": "local", "GOFLAGS": "-mod=mod"},
            )
        )
    return out


def _user() -> str:
    """Who runs inside: the copy's owner on Linux and macOS, so it can write there; never root."""
    getuid = getattr(os, "getuid", None)
    if getuid is None or getuid() == 0:
        return "1000:1000"
    return f"{getuid()}:{os.getgid()}"


def _docker_args(copy: Path, plan: Plan, network: bool, script: str, name: str) -> list[str]:
    workdir = f"/work/{plan.folder}" if plan.folder else "/work"
    args = [
        "run", "--rm", "--name", name,
        "-v", f"{copy}:/work",
        "-w", workdir,
        "--user", _user(),
        "-e", "HOME=/tmp", "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1", "-e", "CI=1",
        *[a for k, v in plan.env.items() for a in ("-e", f"{k}={v}")],
        "--tmpfs", "/tmp:rw,exec,size=1g",
        *LIMITS,
    ]
    if not network:
        args += ["--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    args += [plan.image, "sh", "-c", script]
    return args


def parse_junit(text: str, root: str = "") -> list[TestCase]:
    out: list[TestCase] = []
    try:
        tree = ET.fromstring(text)
    except ET.ParseError:
        return out
    for case in tree.iter("testcase"):
        outcome, message = "passed", ""
        for tag in ("failure", "error", "skipped"):
            el = case.find(tag)
            if el is not None:
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                message = ((el.get("message") or "") + "\n" + (el.text or "")).strip()[:2000]
                break
        file = case.get("file")
        if not file and case.get("classname"):
            parts = case.get("classname", "").split(".")
            # tests.unit.test_x.TestThing -> tests/unit/test_x.py
            cut = next((i for i, p in enumerate(parts) if p.startswith("test_") or p.endswith("_test")), len(parts) - 1)
            file = "/".join(parts[: cut + 1]) + ".py"
        if file and root:
            file = f"{root}/{file}"
        line = case.get("line")
        out.append(TestCase(f"{case.get('classname', '')}::{case.get('name', '')}".strip(":"), file, int(line) + 1 if line and line.isdigit() else None, outcome, message))
    return out


def parse_go(text: str, root: str = "") -> list[TestCase]:
    import json

    out: dict[str, TestCase] = {}
    for raw in text.splitlines():
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        test = event.get("Test")
        if not test or event.get("Action") not in ("pass", "fail", "skip", "output"):
            continue
        key = f"{event.get('Package')}::{test}"
        case = out.setdefault(key, TestCase(key, None, None, "passed"))
        if event["Action"] == "output":
            case.message = (case.message + event.get("Output", ""))[-2000:]
        else:
            case.outcome = {"pass": "passed", "fail": "failed", "skip": "skipped"}[event["Action"]]
    return list(out.values())


async def run_offline(
    runner: Runner, copy: Path, plan: Plan, command: str, token: CancellationToken | None, name: str,
    timeout: float = TEST_TIMEOUT,
) -> Ran:
    """One command in a container with no network, after the install: tests, tools, designed tests."""
    activate = ". /work/.venv/bin/activate && " if plan.runtime == "Python" else ""
    return await runner(_docker_args(copy, plan, False, activate + command, name), timeout, token)


def parse_jest(text: str) -> list[TestCase]:
    """`jest --json` output."""
    import json

    try:
        data = json.loads(text)
    except ValueError:
        return []
    out: list[TestCase] = []
    for suite in data.get("testResults") or []:
        for a in suite.get("assertionResults") or []:
            outcome = {"passed": "passed", "failed": "failed", "pending": "skipped", "skipped": "skipped", "todo": "skipped"}.get(
                a.get("status"), "error"
            )
            out.append(
                TestCase(
                    a.get("fullName") or a.get("title") or "",
                    suite.get("name"),
                    None,
                    outcome,
                    "\n".join(a.get("failureMessages") or [])[:2000],
                )
            )
        if not suite.get("assertionResults") and suite.get("status") == "failed":
            out.append(TestCase(suite.get("name") or "suite", suite.get("name"), None, "error", (suite.get("message") or "")[:2000]))
    return out


async def run_plan(runner: Runner, copy: Path, plan: Plan, token: CancellationToken | None, tag: str) -> SandboxResult:
    result = SandboxResult(plan=plan, installed=False)
    (copy / OUT).mkdir(exist_ok=True)
    install_script = " && ".join(plan.install)
    result.install = await runner(_docker_args(copy, plan, True, install_script, f"codelith-qa-{tag}-install"), INSTALL_TIMEOUT, token)
    if result.install.exit_code != 0 or result.install.timed_out:
        return result
    result.installed = True
    result.test = await run_offline(runner, copy, plan, plan.test, token, f"codelith-qa-{tag}-test")
    if plan.report == "junit":
        junit = copy / OUT / "junit.xml"
        if junit.is_file():
            result.cases = parse_junit(junit.read_text(encoding="utf-8", errors="replace"), plan.folder)
    elif plan.report == "gojson":
        result.cases = parse_go(result.test.output, plan.folder)
    for tool, command in plan.tools:
        result.tools[tool] = await run_offline(runner, copy, plan, command, token, f"codelith-qa-{tag}-{tool.replace(' ', '-')}")
    return result


def remove(copy: Path) -> None:
    shutil.rmtree(copy, ignore_errors=True)


__all__ = [
    "OUT",
    "Plan",
    "Ran",
    "Runner",
    "SandboxResult",
    "TestCase",
    "docker_ready",
    "parse_go",
    "parse_jest",
    "parse_junit",
    "plans",
    "remove",
    "run_offline",
    "run_plan",
]
