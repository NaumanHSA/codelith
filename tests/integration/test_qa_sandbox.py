"""
Run tests, against a stand-in for `docker`: what goes into each container, and what
comes back out as findings. Nothing here starts a container.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from codelith.apps.qa import designed, sandbox
from codelith.apps.qa.findings import Finding
from codelith.apps.qa.service import QAService, steps_for
from codelith.db.repositories.knowledge.source_repo import SnapshotFile, SourceRepository
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.detectors import project_file_kind, project_file_language
from codelith.knowledge.runbook import Need, Runbook, Step
from codelith.models.knowledge import KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project
from codelith.models.qa import QADesignedTest, QAFinding, QARun

FILES = {
    "pyproject.toml": (
        '[project]\nname = "shop"\nrequires-python = ">=3.11"\ndependencies = ["fastapi>=0.110"]\n\n'
        '[project.optional-dependencies]\ndev = ["pytest>=8", "ruff>=0.5"]\n'
    ),
    "app/core.py": "def add(a, b):\n    return a + b\n\n\ndef divide(a, b):\n    return a / b\n",
    "tests/test_core.py": "from app.core import add, divide\n\n\ndef test_adds():\n    assert add(1, 2) == 3\n\n\ndef test_divides():\n    assert divide(1, 0) == 0\n",
    ".env": "SECRET_KEY=•••\n",
}

FILES["app/io.py"] = "def read(path):\n    try:\n        return open(path).read()\n    except:\n        return None\n"

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2" failures="1">
<testcase classname="tests.test_core" name="test_adds" file="tests/test_core.py" line="3" time="0.01"/>
<testcase classname="tests.test_core" name="test_divides" file="tests/test_core.py" line="7" time="0.01">
<failure message="ZeroDivisionError: division by zero">def test_divides():
&gt;       assert divide(1, 0) == 0
E       ZeroDivisionError: division by zero</failure></testcase>
</testsuite></testsuites>
"""

RUFF = [
    {"code": "F821", "message": "Undefined name `total`", "filename": "/work/app/core.py", "location": {"row": 6, "column": 12}, "fix": None},
    {"code": "E501", "message": "Line too long (130 > 120)", "filename": "/work/app/core.py", "location": {"row": 1, "column": 1}},
    {"code": "F821", "message": "Undefined name `x`", "filename": "/work/build/gen.py", "location": {"row": 1, "column": 1}},
]


DESIGNED_FAIL = """<testsuites><testsuite tests="2" failures="1">
<testcase classname="tests.test_codelith_qa_1" name="test_divides_evenly" file="tests/test_codelith_qa_1.py" line="3"/>
<testcase classname="tests.test_codelith_qa_1" name="test_divide_by_zero_raises_value_error" file="tests/test_codelith_qa_1.py" line="7">
<failure message="ZeroDivisionError: division by zero">E   ZeroDivisionError: division by zero</failure></testcase>
</testsuite></testsuites>"""
DESIGNED_BROKEN = """<testsuites><testsuite tests="1" errors="1">
<testcase classname="" name="tests.test_codelith_qa_1"><error message="collection failure">ImportError: cannot import name 'divid' from 'app.core'</error></testcase>
</testsuite></testsuites>"""
DESIGNED_PASS = """<testsuites><testsuite tests="1">
<testcase classname="tests.test_codelith_qa_1" name="test_divides_evenly" file="tests/test_codelith_qa_1.py" line="3"/>
</testsuite></testsuites>"""


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    """Nothing in this file may reach a configured model."""
    from codelith.llm import client as llm

    async def refuse(*_a, **_kw):
        raise AssertionError("a test reached the model")

    monkeypatch.setattr(llm, "chat_completion", refuse)


class FakeDocker:
    """Answers like `docker` would, and remembers what it was asked."""

    def __init__(self, *, running: bool = True, install_fails: bool = False, designed: tuple[str, ...] = ()) -> None:
        self.running = running
        self.install_fails = install_fails
        self.calls: list[list[str]] = []
        self.seen_files: set[str] = set()
        #: The JUnit report each designed-test run writes, in turn.
        self.designed = list(designed)
        self.designed_files: list[str] = []
        self.verify_report: str | None = None
        self.verified_with: str | None = None

    async def __call__(self, args, timeout, token):
        self.calls.append(list(args))
        if args[0] == "info":
            return sandbox.Ran(0, "27.3.1\n", 0.1) if self.running else sandbox.Ran(1, "error during connect", 0.1)
        copy = Path(args[args.index("-v") + 1].rsplit(":/work", 1)[0])
        name = args[args.index("--name") + 1]
        if name.endswith("-install"):
            self.seen_files = {p.relative_to(copy).as_posix() for p in copy.rglob("*") if p.is_file()}
            if self.install_fails:
                return sandbox.Ran(1, "Collecting fastapi>=0.110\nERROR: No matching distribution found for fastapi>=0.110\n", 4.0)
            return sandbox.Ran(0, "installed\n", 30.0)
        if name.endswith("-test"):
            (copy / sandbox.OUT / "junit.xml").write_text(JUNIT, encoding="utf-8")
            return sandbox.Ran(1, "1 failed, 1 passed\n", 2.0)
        if name.endswith("-ruff"):
            return sandbox.Ran(0, json.dumps(RUFF), 1.0)
        if name.endswith("-verify"):
            self.verified_with = (copy / "app/io.py").read_text(encoding="utf-8")
            (copy / sandbox.OUT / "junit.xml").write_text(self.verify_report or JUNIT, encoding="utf-8")
            return sandbox.Ran(1, "1 failed, 1 passed\n", 2.0)
        if "-designed-" in name:
            n = name.rsplit("-", 1)[1]
            test = copy / f"tests/test_codelith_qa_{n}.py"
            self.designed_files.append(test.read_text(encoding="utf-8"))
            report = self.designed.pop(0)
            (copy / sandbox.OUT / f"designed-{n}.xml").write_text(report, encoding="utf-8")
            return sandbox.Ran(0 if report is DESIGNED_PASS else 1, "pytest output\n", 1.5)
        raise AssertionError(f"unexpected container {name}")

    def container(self, suffix: str) -> list[str]:
        return next(c for c in self.calls if c[0] == "run" and c[c.index("--name") + 1].endswith(suffix))


@pytest_asyncio.fixture
async def kb(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-qs-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="shop", slug=f"shop-qs-{tag}")
    db_session.add(project)
    await db_session.flush()
    kb = KnowledgeBase(project_id=project.id, commit_sha=uuid.uuid4().hex, status=KBStatus.READY)
    db_session.add(kb)
    await db_session.flush()
    await SourceRepository(db_session).store(
        kb.id,
        [
            SnapshotFile(
                path=p,
                content=c,
                language=project_file_language(p) if project_file_kind(p) else "python",
                kind=project_file_kind(p),
                masked=p == ".env",
            )
            for p, c in FILES.items()
        ],
    )
    await db_session.commit()
    return kb


async def _run(db_session, kb, docker: FakeDocker, monkeypatch, depth: str = "tests", areas=("tests", "breaks")):
    monkeypatch.setattr(sandbox, "Runner", lambda: docker)
    run = QARun(project_id=kb.project_id, kb_id=kb.id, areas_json=list(areas), scope_json={"kind": "all"}, depth=depth)
    db_session.add(run)
    await db_session.commit()
    await QAService(db_session).execute(run.id)
    found = list((await db_session.execute(select(QAFinding).where(QAFinding.run_id == run.id))).scalars())
    return run, found


class TestRunTests:
    async def test_a_failing_test_and_an_undefined_name_are_confirmed_findings(self, db_session, kb, monkeypatch) -> None:
        docker = FakeDocker()
        run, found = await _run(db_session, kb, docker, monkeypatch)
        assert run.status == "completed"
        failing = [f for f in found if f.rule == "tests.failing"]
        assert [(f.title, f.path, f.line, f.source, f.confidence) for f in failing] == [
            ("`test_divides` fails", "tests/test_core.py", 8, "test", "confirmed")
        ]
        assert "ZeroDivisionError" in failing[0].message
        tools = [(f.rule, f.path, f.line, f.severity, f.area) for f in found if f.source == "tool"]
        # E501 is style, not QA's; `build/gen.py` is not a file of the reading.
        assert tools == [("tool.ruff", "app/core.py", 6, "high", "breaks")]
        note = next(n for n in run.summary_json["notes"] if n.startswith("Ran 2 Python tests"))
        assert "1 passed, 1 failed, 0 skipped" in note

    async def test_the_tests_run_with_no_network_and_none_of_this_machines_environment(self, db_session, kb, monkeypatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "must-not-travel")
        docker = FakeDocker()
        await _run(db_session, kb, docker, monkeypatch)
        install, test = docker.container("-install"), docker.container("-test")
        assert "--network" not in install, "the install needs the network to fetch packages"
        for flag in ("--network", "--read-only", "--cap-drop", "--security-opt"):
            assert flag in test
        assert test[test.index("--network") + 1] == "none"
        assert test[-3:-1] == ["sh", "-c"] and "pytest" in test[-1]
        for call in (install, test):
            values = [call[i + 1] for i, a in enumerate(call) if a == "-e"]
            assert not any("must-not-travel" in v or v.startswith("OPENAI") for v in values)
            assert call[call.index("--user") + 1] != "0:0"
        assert install[install.index("--memory") + 1] == "3g"
        assert install[-1].startswith("python -m venv /work/.venv")
        assert 'pip install -q -e ".[dev]"' in install[-1] and "pytest ruff" in install[-1]
        assert any(c[0] == "run" and "ruff check" in c[-1] for c in docker.calls)

    async def test_the_copy_holds_the_kept_files_but_never_a_real_env_and_is_removed(self, db_session, kb, monkeypatch) -> None:
        docker = FakeDocker()
        run, _ = await _run(db_session, kb, docker, monkeypatch)
        assert {"pyproject.toml", "app/core.py", "tests/test_core.py"} <= docker.seen_files
        assert ".env" not in docker.seen_files
        copy = Path(docker.container("-install")[docker.container("-install").index("-v") + 1].rsplit(":/work", 1)[0])
        assert not copy.exists()
        assert any("files the reading kept" in n for n in run.summary_json["notes"])

    async def test_a_clean_install_that_fails_is_one_finding_and_nothing_else_runs(self, db_session, kb, monkeypatch) -> None:
        docker = FakeDocker(install_fails=True)
        run, found = await _run(db_session, kb, docker, monkeypatch)
        assert [(f.rule, f.severity, f.path) for f in found] == [("breaks.install-fails", "high", "pyproject.toml")]
        assert "No matching distribution" in found[0].message
        assert [c for c in docker.calls if c[0] == "run" and not c[c.index("--name") + 1].endswith("-install")] == []

    async def test_docker_not_running_is_said_not_failed(self, db_session, kb, monkeypatch) -> None:
        docker = FakeDocker(running=False)
        run, found = await _run(db_session, kb, docker, monkeypatch)
        assert run.status == "completed" and found == []
        assert any("Docker is installed but not running" in n for n in run.summary_json["notes"])

    async def test_a_quick_run_never_asks_docker(self, db_session, kb, monkeypatch) -> None:
        docker = FakeDocker()
        await _run(db_session, kb, docker, monkeypatch, depth="quick")
        assert docker.calls == []
        assert "qa_sandbox" not in steps_for(["tests"], depth="thorough")
        assert "qa_sandbox" in steps_for(["tests"], depth="tests")


class TestPlans:
    def _book(self, needs, install=(), test=()):
        return Runbook(
            available=True,
            needs=[Need(w, v, "x", "runtime") for w, v in needs],
            install=[Step(c, "", "x") for c in install],
            test=[Step(c, "", "x") for c in test],
        )

    def test_pnpm_goes_through_corepack_with_its_cache_in_the_copy(self) -> None:
        book = self._book([("Node.js", ">=20.19")], install=["cd ui && pnpm install"], test=["cd ui && pnpm test"])
        (plan,) = sandbox.plans(book, {"Node.js": {"typescript"}}, {"Node.js": True})
        assert (plan.image, plan.folder, plan.install, plan.test) == ("node:20-slim", "ui", ["corepack pnpm install"], "corepack pnpm test")
        assert plan.env["COREPACK_HOME"].startswith("/work/")
        assert [t for t, _ in plan.tools] == ["tsc"]

    def test_go_keeps_its_modules_in_the_copy_for_the_offline_container(self) -> None:
        (plan,) = sandbox.plans(self._book([("Go", "1.22")]), {}, {"Go": True})
        assert plan.image == "golang:1.22" and plan.report == "gojson"
        assert plan.env["GOMODCACHE"].startswith("/work/") and plan.env["GOTOOLCHAIN"] == "local"

    def test_nothing_to_run_without_test_files_and_make_targets_are_skipped(self) -> None:
        book = self._book([("Python", "3.12")], install=["make install", "pip install -r requirements.txt"])
        assert sandbox.plans(book, {}, {"Python": False}) == []
        (plan,) = sandbox.plans(book, {}, {"Python": True})
        assert "make install" not in " ".join(plan.install)
        assert "pip install -q -r requirements.txt" in plan.install
        assert plan.tools == []

    def test_python_folder_comes_from_the_install_step(self) -> None:
        book = self._book([("Python", ">=3.11")], install=["cd api && pip install -e ."])
        (plan,) = sandbox.plans(book, {"Python": {"mypy"}}, {"Python": True})
        assert plan.folder == "api" and plan.image == "python:3.11-slim"
        assert [t for t, _ in plan.tools] == ["mypy"]


class TestReports:
    def test_junit_without_file_attributes_maps_the_class_to_a_path(self) -> None:
        text = (
            '<testsuite><testcase classname="tests.unit.test_x.TestThing" name="test_a"/>'
            '<testcase classname="tests.unit.test_x" name="test_b"><skipped message="later"/></testcase></testsuite>'
        )
        cases = sandbox.parse_junit(text, "api")
        assert [(c.file, c.outcome) for c in cases] == [("api/tests/unit/test_x.py", "passed"), ("api/tests/unit/test_x.py", "skipped")]

    def test_go_json_events_become_cases(self) -> None:
        events = [
            {"Action": "run", "Package": "shop/core", "Test": "TestAdd"},
            {"Action": "output", "Package": "shop/core", "Test": "TestAdd", "Output": "core_test.go:9: got 2\n"},
            {"Action": "fail", "Package": "shop/core", "Test": "TestAdd"},
            {"Action": "pass", "Package": "shop/core", "Test": "TestSub"},
            {"Action": "pass", "Package": "shop/core"},
        ]
        cases = sandbox.parse_go("\n".join(json.dumps(e) for e in events) + "\nnot json\n")
        assert [(c.name, c.outcome) for c in cases] == [("shop/core::TestAdd", "failed"), ("shop/core::TestSub", "passed")]
        assert "got 2" in cases[0].message

    @pytest.mark.parametrize(
        ("tool", "line", "expected"),
        [
            ("mypy", "app/core.py:6:12: error: Name \"total\" is not defined  [name-defined]", ("app/core.py", 6, "medium")),
            ("mypy", "app/core.py:1: error: Library stubs not installed for \"yaml\"  [import-untyped]", None),
            ("tsc", "src/App.tsx(12,5): error TS2339: Property 'x' does not exist on type 'Y'.", ("src/App.tsx", 12, "medium")),
            ("go vet", "./core/add.go:7:2: unreachable code", ("core/add.go", 7, "medium")),
        ],
    )
    def test_tool_output_lines(self, tool, line, expected) -> None:
        from codelith.apps.qa.checks.sandbox import _tool_findings

        found = _tool_findings(tool, sandbox.Ran(0, line + "\n", 1.0), "")
        assert [(f.path, f.line, f.severity) for f in found] == ([expected] if expected else [])


V1 = "from app.core import divid\n\n\ndef test_divide_by_zero_raises_value_error():\n    divid(1, 0)\n"
V2 = (
    "import pytest\n\nfrom app.core import divide\n\n\ndef test_divides_evenly():\n    assert divide(6, 3) == 2\n\n\n"
    "def test_divide_by_zero_raises_value_error():\n    with pytest.raises(ValueError):\n        divide(1, 0)\n"
)


class FakeModel:
    def __init__(self, verdicts: list[dict]) -> None:
        self.verdicts = list(verdicts)
        self.calls: list[str] = []

    async def __call__(self, messages, spec=None, **_kw):
        system = messages[0]["content"]
        if "You design and write tests" in system:
            self.calls.append("design")
            assert "from app.core import divide" in system and "pytest" in system
            assert "no network" in system and "fastapi" in system
            return json.dumps({
                "cases": [
                    {"name": "test_divides_evenly", "checks": "an even division", "expect": "6 / 3 is 2"},
                    {"name": "test_divide_by_zero_raises_value_error", "checks": "dividing by zero", "expect": "a ValueError"},
                ],
                "code": "```python\n" + V1 + "```",
            })
        self.calls.append("verdict")
        assert "has failed" in system
        return json.dumps(self.verdicts.pop(0))


class TestDesignedTests:
    @pytest.fixture
    def divide(self, monkeypatch):
        async def chosen(ctx, plan, budget):
            return [designed.Target("app/core.py", "divide", 5, 6, "untested")]

        monkeypatch.setattr(designed, "targets", chosen)

    async def test_a_wrong_test_is_corrected_and_a_real_failure_becomes_a_finding(self, db_session, kb, monkeypatch, divide) -> None:
        from codelith.llm import client as llm

        model = FakeModel([
            {"verdict": "wrong_test", "why": "It imports a name that does not exist.", "code": V2},
            {"verdict": "bug", "why": "Dividing by zero raises ZeroDivisionError, not a clear error.", "severity": "high",
             "line": 6, "fix": "Check b before dividing."},
        ])
        monkeypatch.setattr(llm, "chat_completion", model)
        docker = FakeDocker(designed=(DESIGNED_BROKEN, DESIGNED_FAIL))
        run, found = await _run(db_session, kb, docker, monkeypatch)

        assert model.calls == ["design", "verdict", "verdict"]
        assert docker.designed_files == [V1, V2], "the fenced code is unwrapped, then replaced by the correction"
        call = docker.container("-designed-1")
        assert call[call.index("--network") + 1] == "none"
        assert "pytest" in call[-1] and call[-1].endswith("tests/test_codelith_qa_1.py")

        (bug,) = [f for f in found if f.rule == "tests.designed-fails"]
        assert (bug.path, bug.line, bug.severity, bug.confidence, bug.source) == ("app/core.py", 6, "high", "likely", "test")
        assert "ZeroDivisionError" in bug.message and bug.fix == "Check b before dividing."

        rows = list((await db_session.execute(select(QADesignedTest).where(QADesignedTest.run_id == run.id))).scalars())
        (row,) = rows
        assert (row.outcome, row.tries, row.file_path, row.code, row.reason) == ("bug", 2, "tests/test_codelith_qa_1.py", V2, "untested")
        assert [c["name"] for c in row.cases_json] == ["test_divides_evenly", "test_divide_by_zero_raises_value_error"]
        assert [(r["name"], r["outcome"]) for r in row.results_json] == [
            ("test_divides_evenly", "passed"), ("test_divide_by_zero_raises_value_error", "failed")
        ]
        assert row.finding_fingerprint == bug.fingerprint
        assert run.summary_json["designed"] == {"bug": 1}
        assert any("designed tests for 1 Python function(s) in 3 call(s): 0 passed, 1 found a bug" in n for n in run.summary_json["notes"])

    async def test_a_passing_test_is_kept_and_raises_nothing(self, db_session, kb, monkeypatch, divide) -> None:
        from codelith.llm import client as llm

        model = FakeModel([])
        monkeypatch.setattr(llm, "chat_completion", model)
        docker = FakeDocker(designed=(DESIGNED_PASS,))
        run, found = await _run(db_session, kb, docker, monkeypatch)
        assert model.calls == ["design"]
        assert not [f for f in found if f.rule == "tests.designed-fails"]
        row = (await db_session.execute(select(QADesignedTest).where(QADesignedTest.run_id == run.id))).scalar_one()
        assert (row.outcome, row.tries) == ("passed", 1)

    async def test_given_up_after_two_corrections(self, db_session, kb, monkeypatch, divide) -> None:
        from codelith.llm import client as llm

        model = FakeModel([{"verdict": "wrong_test", "why": "Still wrong.", "code": V1}] * 3)
        monkeypatch.setattr(llm, "chat_completion", model)
        docker = FakeDocker(designed=(DESIGNED_BROKEN,) * 3)
        run, found = await _run(db_session, kb, docker, monkeypatch)
        row = (await db_session.execute(select(QADesignedTest).where(QADesignedTest.run_id == run.id))).scalar_one()
        assert (row.outcome, row.tries) == ("wrong", 3)
        assert model.calls == ["design", "verdict", "verdict", "verdict"]
        assert not [f for f in found if f.rule == "tests.designed-fails"]

    async def test_a_model_that_fails_stops_the_design_not_the_run(self, db_session, kb, monkeypatch, divide) -> None:
        from codelith.llm import client as llm

        async def down(*_a, **_kw):
            raise ConnectionError("refused")

        monkeypatch.setattr(llm, "chat_completion", down)
        run, found = await _run(db_session, kb, FakeDocker(), monkeypatch)
        assert run.status == "completed"
        assert any(f.rule == "tests.failing" for f in found), "the codebase's own tests still count"
        assert any("could not be reached (ConnectionError)" in n for n in run.summary_json["notes"])


class TestChoosingWhatToTest:
    async def test_a_suspected_finding_comes_before_untested_code(self, monkeypatch) -> None:
        from types import SimpleNamespace

        suspected = Finding("review.errors", "errors", "medium", "Refund issued twice", "m", "f", path="app/pay.py", line=12,
                            confidence="suspected", source="model")
        certain = Finding("py.bare-except", "errors", "low", "Bare except", "m", "f", path="app/pay.py", line=30)
        ra = SimpleNamespace(symbols={"app/pay.py": [("Pay", 1, 40), ("Pay.refund", 10, 20), ("Pay.charge", 25, 35)]})

        async def fake_access(ctx):
            return ra

        async def fake_risky(ctx, budget, keep, untested_only):
            assert untested_only and keep("app/pay.py") and not keep("tests/test_pay.py") and not keep("ui/app.ts")
            return [(9.0, "app/pay.py", "Pay.refund", 10, 20), (5.0, "app/pay.py", "Pay._log", 36, 39), (4.0, "app/ship.py", "ship", 1, 9)]

        monkeypatch.setattr(designed, "route_access", fake_access)
        monkeypatch.setattr(designed, "risky", fake_risky)
        ctx = SimpleNamespace(cache={"found": [certain, suspected]})
        plan = sandbox.Plan("Python", "python:3.12-slim", "", [], "", "junit")
        chosen = await designed.targets(ctx, plan, 3)
        assert [(t.name, t.reason) for t in chosen] == [("Pay.refund", "finding"), ("ship", "untested")]
        assert chosen[0].finding is suspected

    def test_a_reproduced_finding_becomes_likely_and_no_new_one_is_made(self) -> None:
        f = Finding("review.errors", "errors", "medium", "Refund issued twice", "Seen in review.", "f", path="app/pay.py",
                    line=12, confidence="suspected", source="model")
        target = designed.Target("app/pay.py", "Pay.refund", 10, 20, "finding", f)
        d = designed.Designed(target, "Python", "pytest", "tests/test_codelith_qa_1.py", verdict="It refunds twice.")
        case = sandbox.TestCase("t::test_refund_once", None, None, "failed", "assert 2 == 1")
        assert designed._judged_bug(target, d, {"verdict": "bug"}, [case], "assert 2 == 1") is f
        assert f.confidence == "likely" and f.evidence["reproduced_by"] == "tests/test_codelith_qa_1.py"
        assert "A test designed to reproduce it fails (`test_refund_once`): It refunds twice." in f.message

    def test_where_each_runtime_puts_its_test(self) -> None:
        from types import SimpleNamespace

        ctx = SimpleNamespace(all_files=[SimpleNamespace(path="api/spec/test_a.py", kind=None)])
        py = sandbox.Plan("Python", "python:3.12-slim", "api", [], "", "junit")
        where, hint = designed.placement(ctx, py, "pytest", designed.Target("api/src/shop/core.py", "Cart.total", 1, 9, "untested"), 2, "")
        assert where == "api/spec/test_codelith_qa_2.py" and "from shop.core import Cart" in hint
        go = sandbox.Plan("Go", "golang:1.22", "", [], "", "gojson")
        where, hint = designed.placement(ctx, go, "go test", designed.Target("core/add.go", "Add", 3, 9, "untested"), 1, "package core\n")
        assert where == "core/codelith_qa_1_test.go" and "package core" in hint
        node = sandbox.Plan("Node.js", "node:20-slim", "ui", [], "pnpm test", "exit")
        where, hint = designed.placement(ctx, node, "vitest", designed.Target("ui/src/lib/money.ts", "format", 3, 9, "untested"), 1, "")
        assert where == "ui/src/lib/money.codelith-qa-1.test.ts" and "./money" in hint
        assert designed.framework_for(node, {"vitest"}) == "vitest" and designed.framework_for(node, set()) is None

    def test_jest_json(self) -> None:
        report = {"testResults": [{"name": "/work/ui/a.test.ts", "assertionResults": [
            {"fullName": "money formats", "status": "passed"},
            {"fullName": "money rounds", "status": "failed", "failureMessages": ["Expected 1.01"]},
        ]}]}
        cases = sandbox.parse_jest(json.dumps(report))
        assert [(c.name, c.outcome, c.message) for c in cases] == [("money formats", "passed", ""), ("money rounds", "failed", "Expected 1.01")]


class TestOverHttp:
    async def test_the_designed_tests_their_archive_and_the_finding_that_names_one(self, db_session, kb, client, monkeypatch) -> None:
        import io
        import zipfile

        from codelith.core.security import create_access_token
        from codelith.llm import client as llm
        from codelith.models.user import User

        async def chosen(ctx, plan, budget):
            return [designed.Target("app/core.py", "divide", 5, 6, "untested")]

        monkeypatch.setattr(designed, "targets", chosen)
        monkeypatch.setattr(llm, "chat_completion", FakeModel([
            {"verdict": "wrong_test", "why": "Wrong name.", "code": V2},
            {"verdict": "bug", "why": "No clear error on zero.", "severity": "medium", "line": 6, "fix": "Check b."},
        ]))
        run, found = await _run(db_session, kb, FakeDocker(designed=(DESIGNED_BROKEN, DESIGNED_FAIL)), monkeypatch)
        project = await db_session.get(Project, kb.project_id)
        user = User(org_id=project.org_id, email=f"qs-{uuid.uuid4().hex[:8]}@example.com", password_hash="x",
                    full_name="QS", role="manager", is_active=True)
        db_session.add(user)
        await db_session.flush()
        headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
        base = f"/api/v1/projects/{kb.project_id}/qa"

        listed = (await client.get(f"{base}/runs/{run.id}/designed", headers=headers)).json()
        assert [(d["outcome"], d["file_path"], d["tries"]) for d in listed] == [("bug", "tests/test_codelith_qa_1.py", 2)]

        archive = await client.get(f"{base}/runs/{run.id}/designed/archive", headers=headers)
        assert archive.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            assert sorted(z.namelist()) == ["README-codelith-qa.md", "tests/test_codelith_qa_1.py"]
            assert z.read("tests/test_codelith_qa_1.py").decode() == V2
            assert "No clear error on zero." in z.read("README-codelith-qa.md").decode()

        bug = next(f for f in found if f.rule == "tests.designed-fails")
        detail = (await client.get(f"{base}/findings/{bug.id}", headers=headers)).json()
        assert detail["designed_test"]["code"] == V2
        other = next(f for f in found if f.rule == "tests.failing")
        assert (await client.get(f"{base}/findings/{other.id}", headers=headers)).json()["designed_test"] is None


class TestFixesCheckedInTheSandbox:
    async def test_a_patch_is_applied_the_tests_run_again_and_it_says_so(self, db_session, kb, monkeypatch) -> None:
        docker = FakeDocker()
        run, found = await _run(db_session, kb, docker, monkeypatch, areas=("tests", "breaks", "errors"))
        bare = next(f for f in found if f.rule == "py.bare-except")
        assert bare.patch and "+    except Exception:" in bare.patch
        assert "    except Exception:" in docker.verified_with, "the copy had the fix applied when the tests ran"
        assert bare.evidence_json["verified"].startswith("With this change applied, the 2 Python tests ran again")
        assert any("suggested fix(es) were applied in the sandbox" in n for n in run.summary_json["notes"])

    async def test_a_fix_that_breaks_a_test_is_not_marked(self, db_session, kb, monkeypatch) -> None:
        docker = FakeDocker()
        docker.verify_report = JUNIT.replace('line="3" time="0.01"/>', 'line="3" time="0.01"><failure message="boom">x</failure></testcase>', 1)
        run, found = await _run(db_session, kb, docker, monkeypatch, areas=("tests", "breaks", "errors"))
        bare = next(f for f in found if f.rule == "py.bare-except")
        assert bare.patch and "verified" not in bare.evidence_json
        assert any("newly failed (test_adds)" in n for n in run.summary_json["notes"])
