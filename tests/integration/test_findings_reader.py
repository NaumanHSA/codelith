"""
QA's findings as the rest of Codelith reads them (`knowledge/findings.py`): which are
open, which areas were never checked, and what Ask, MCP, the pre-flight and a review
make of them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest_asyncio

from codelith.knowledge.changes import ChangedFile, ChangeSet
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.findings import FindingsReader, areas_asked
from codelith.knowledge.preflight import Preflight, PreflightService
from codelith.knowledge.questions import EvidenceBundle, QuestionPlan, QuestionRouter
from codelith.knowledge.review import Review, ReviewService
from codelith.knowledge.tools import CodebaseTools
from codelith.models.knowledge import KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project
from codelith.models.qa import QAFinding, QAFindingState, QARun

CODE = "def load(path):\n    try:\n        return open(path).read()\n    except:\n        return None\n"


def _finding(run, project_id, fp, area, severity, title, path="app/io.py", line=4, rule="x.rule", source="check", snippet=""):
    return QAFinding(
        run_id=run.id, project_id=project_id, fingerprint=fp, rule=rule, area=area, severity=severity,
        confidence="confirmed", source=source, title=title, message="Why it matters.", fix="Do this.",
        path=path, line=line, snippet=snippet,
    )


@pytest_asyncio.fixture
async def project(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-fr-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="shop", slug=f"shop-fr-{tag}")
    db_session.add(project)
    await db_session.flush()
    kb = KnowledgeBase(project_id=project.id, commit_sha="b" * 40, status=KBStatus.READY)
    db_session.add(kb)
    await db_session.flush()

    older = QARun(project_id=project.id, kb_id=kb.id, areas_json=["security", "errors"], scope_json={"kind": "all"},
                  status="completed", summary_json={"commit": "a" * 40}, finished_at=datetime(2026, 11, 1, tzinfo=UTC))
    db_session.add(older)
    await db_session.flush()
    newer = QARun(project_id=project.id, kb_id=kb.id, areas_json=["security"], scope_json={"kind": "all"},
                  status="completed", summary_json={"commit": "b" * 40}, finished_at=datetime(2026, 11, 10, tzinfo=UTC))
    failed = QARun(project_id=project.id, kb_id=kb.id, areas_json=["tests"], scope_json={"kind": "all"}, status="failed")
    db_session.add_all([newer, failed])
    await db_session.flush()
    db_session.add_all([
        _finding(older, project.id, "old-sec", "security", "high", "Fixed since: only the older run saw it"),
        _finding(older, project.id, "bare", "errors", "medium", "A bare except", rule="py.bare-except", source="rule",
                 snippet="    except:"),
        _finding(newer, project.id, "sql", "security", "critical", "SQL built from input", path="app/db.py", line=12),
        _finding(newer, project.id, "cors", "security", "low", "CORS open", path="app/main.py", line=3),
        _finding(newer, project.id, "dismissed", "security", "high", "Dismissed by someone", path="app/db.py", line=40),
    ])
    db_session.add(QAFindingState(project_id=project.id, fingerprint="dismissed", status="dismissed", reason="test data"))
    await db_session.commit()
    project.kb = kb  # for the tests
    return project


class TestReading:
    async def test_each_area_comes_from_the_latest_run_that_checked_it(self, db_session, project) -> None:
        reader = FindingsReader(db_session, project.id)
        found = await reader.open()
        assert [(k.fingerprint, k.area) for k in found] == [("sql", "security"), ("bare", "errors"), ("cors", "security")]
        coverage = await reader.coverage()
        assert sorted(coverage.areas) == ["errors", "security"]
        assert coverage.unchecked(["security", "tests", "leakage"]) == ["tests", "leakage"], "a failed run checked nothing"
        assert coverage.behind("errors") and not coverage.behind("security")
        assert "never checked by QA" in coverage.brief(["tests"])

    async def test_narrowed_by_path_area_and_severity(self, db_session, project) -> None:
        reader = FindingsReader(db_session, project.id)
        assert [k.fingerprint for k in await reader.open(path="app/db.py")] == ["sql"]
        assert [k.fingerprint for k in await reader.open(path="app")] == ["sql", "bare", "cors"]
        assert [k.fingerprint for k in await reader.open(path="io.py")] == ["bare"]
        assert [k.fingerprint for k in await reader.open(areas=["errors"])] == ["bare"]
        assert [k.fingerprint for k in await reader.open(min_severity="high")] == ["sql"]
        assert await reader.by_path() == {"app/db.py": ("critical", 1), "app/io.py": ("medium", 1), "app/main.py": ("low", 1)}


class TestWhoReadsThem:
    async def test_the_qa_findings_tool(self, db_session, project) -> None:
        tools = CodebaseTools(db_session, project.kb.id, project.id)
        text, evidence = await tools.run("qa_findings", {"area": "security"})
        assert "Security: checked by QA run" in text and "SQL built from input — app/db.py:12" in text
        assert "Dismissed" not in text and "older run" not in text
        assert {e.title for e in evidence} >= {"app/db.py:12", "app/main.py:3", "QA coverage"}
        text, _ = await tools.run("qa_findings", {"area": "tests"})
        assert "never checked by QA" in text and "No open findings" in text

    async def test_the_tool_says_when_qa_never_ran(self, db_session) -> None:
        tag = uuid.uuid4().hex[:8]
        org = Organization(name="o", slug=f"o-fr2-{tag}")
        db_session.add(org)
        await db_session.flush()
        other = Project(org_id=org.id, name="new", slug=f"new-fr-{tag}")
        db_session.add(other)
        await db_session.flush()
        text, _ = await CodebaseTools(db_session, 0, other.id).run("qa_findings", {})
        assert text.startswith("QA has never been run on this codebase")

    async def test_the_preflight_lists_a_files_findings(self, db_session, project) -> None:
        report = Preflight(target="app/db.py", files=["app/db.py"], kind="file")
        await PreflightService(db_session, project.kb.id, project.id)._findings(report)
        assert [k.title for k in report.findings] == ["SQL built from input"]
        assert "Open QA findings here" in report.brief() and "app/db.py:12" in report.brief()

    async def test_a_review_says_what_a_change_fixes_touches_or_removes(self, db_session, project) -> None:
        fixed = CODE.replace("    except:", "    except OSError:")
        change = ChangeSet(base="HEAD", head=None, files=[
            ChangedFile("app/io.py", "modified", old_ranges=[(4, 4)], new_ranges=[(4, 4)], content=fixed),
            ChangedFile("app/db.py", "modified", old_ranges=[(11, 13)], new_ranges=[(11, 14)], content="x = 1\n"),
            ChangedFile("app/main.py", "deleted", old_ranges=[(1, 9)]),
        ])
        report = Review(commit=project.kb.commit_sha, base="HEAD", head=None)
        await ReviewService(db_session, project.kb)._qa(report, change)
        said = {(f.kind, f.severity, f.path) for f in report.findings}
        assert ("qa-fixed", "note", "app/io.py") in said
        assert ("qa-touched", "warn", "app/db.py") in said, "a critical finding's lines changed: check it"
        assert ("qa-gone", "note", "app/main.py") in said
        assert report.qa_open == 3 and len(report.qa_fixed) == 2

    async def test_a_review_that_leaves_the_rule_firing_does_not_say_fixed(self, db_session, project) -> None:
        change = ChangeSet(base="HEAD", head=None, files=[
            ChangedFile("app/io.py", "modified", old_ranges=[(1, 1)], new_ranges=[(1, 1)], content="# a comment\n" + CODE),
        ])
        report = Review(commit=project.kb.commit_sha, base="HEAD", head=None)
        await ReviewService(db_session, project.kb)._qa(report, change)
        assert [f.kind for f in report.findings] == []

    async def test_ask_gets_findings_and_coverage_for_a_question_about_them(self, db_session, project) -> None:
        router = QuestionRouter(db_session, project.kb.id, project.id, use_llm=False)
        bundle = EvidenceBundle(plan=QuestionPlan(question="Is this code secure, and is it tested?"))
        await router._add_findings(bundle, bundle.plan.question)
        assert bundle.plan.qa_areas == ["security", "tests"]
        assert bundle.plan.qa_unchecked == ["tests"]
        titles = [e.title for e in bundle.of_kind("qa")]
        assert titles == ["app/db.py:12", "app/main.py:3", "QA coverage"]

        from codelith.apps.ask.service import _suggest_qa

        assert _suggest_qa(bundle.plan) == {"areas": ["tests"], "reason": "unchecked"}

    async def test_a_question_about_nothing_qa_knows_gets_nothing(self, db_session, project) -> None:
        router = QuestionRouter(db_session, project.kb.id, project.id, use_llm=False)
        bundle = EvidenceBundle(plan=QuestionPlan(question="Where is the order model defined?"))
        await router._add_findings(bundle, bundle.plan.question)
        assert bundle.items == [] and bundle.plan.qa_areas == []


class TestTheVocabulary:
    def test_the_base_names_the_same_areas_as_the_app(self) -> None:
        from codelith.apps.qa.areas import AREAS
        from codelith.knowledge.findings import QA_AREAS

        assert QA_AREAS == {a.id: a.label for a in AREAS}

    def test_questions_map_to_areas(self) -> None:
        assert areas_asked("Are there any SQL injection vulnerabilities?") == ["security"]
        assert areas_asked("does it leak API keys in the logs") == ["leakage"]
        assert areas_asked("which packages are outdated?") == ["dependencies"]
        assert areas_asked("how are exceptions handled") == ["errors"]
        assert areas_asked("what is untested?") == ["tests"]
        assert len(areas_asked("what problems does this code have?")) == 8
        assert areas_asked("where is the order model defined?") == []


class TestOverHttp:
    async def test_the_map_and_the_codebase_page_get_files_and_coverage(self, db_session, project, client) -> None:
        from codelith.core.security import create_access_token
        from codelith.models.user import User

        user = User(org_id=project.org_id, email=f"fr-{uuid.uuid4().hex[:8]}@example.com", password_hash="x",
                    full_name="FR", role="manager", is_active=True)
        db_session.add(user)
        await db_session.flush()
        body = (await client.get(
            f"/api/v1/projects/{project.id}/findings",
            headers={"Authorization": f"Bearer {create_access_token(str(user.id))}"},
        )).json()
        assert [(c["area"], c["behind"]) for c in body["checked"]] == [("security", False), ("errors", True)]
        assert "tests" in body["unchecked"] and body["open"] == {"critical": 1, "medium": 1, "low": 1}
        assert [(f["path"], f["worst"]) for f in body["files"]] == [("app/db.py", "critical"), ("app/io.py", "medium"), ("app/main.py", "low")]
