"""
A QA run end to end on a reading's kept files: what it finds, what it says each finding
touches, what is new and what was fixed against the run before, decisions that survive
a re-run, and a line that silences itself.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy import select

from codelith.apps.qa.areas import AREA_IDS
from codelith.apps.qa.service import QAService
from codelith.db.repositories.knowledge.source_repo import SnapshotFile, SourceRepository
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.detectors import project_file_kind, project_file_language
from codelith.models.knowledge import KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project
from codelith.models.qa import QAFinding, QARun
from codelith.models.user import User

APP = (
    "import pickle\n"
    "\n"
    "\n"
    "def load(blob):\n"
    "    try:\n"
    "        return pickle.loads(blob)\n"
    "    except Exception:\n"
    "        pass\n"
)
FILES = {
    "app/store.py": APP,
    "app/quiet.py": "def f(x):\n    return eval(x)  # codelith: ignore\n",
    "Dockerfile": "FROM python\nCOPY . .\n",
    ".env": "DATABASE_URL=•••\n",
}


@pytest_asyncio.fixture
async def project(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-qa-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="shop", slug=f"shop-qa-{tag}")
    db_session.add(project)
    await db_session.flush()
    return project


@pytest_asyncio.fixture
async def user(db_session, project):
    user = User(email=f"qa-{uuid.uuid4().hex[:6]}@example.invalid", password_hash="x", org_id=project.org_id)
    db_session.add(user)
    await db_session.flush()
    return user


async def _reading(db_session, project, files: dict[str, str]) -> KnowledgeBase:
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
            for p, c in files.items()
        ],
    )
    await db_session.flush()
    return kb


async def _run(db_session, project, kb, areas=AREA_IDS, scope=None) -> tuple[QARun, list[QAFinding]]:
    run = QARun(project_id=project.id, kb_id=kb.id, areas_json=list(areas), scope_json=scope or {"kind": "all"})
    db_session.add(run)
    await db_session.commit()
    await QAService(db_session).execute(run.id)
    rows = (await db_session.execute(select(QAFinding).where(QAFinding.run_id == run.id))).scalars().all()
    return run, list(rows)


class TestARun:
    async def test_it_finds_and_says_what_it_found(self, db_session, project) -> None:
        kb = await _reading(db_session, project, FILES)
        run, found = await _run(db_session, project, kb)
        assert run.status == "completed"
        rules = {f.rule for f in found}
        assert {"py.unsafe-deserialization", "py.swallowed-exception", "config.docker-root", "config.docker-copies-everything", "leak.env-committed"} <= rules
        assert "py.eval" not in rules  # silenced on its own line
        assert run.summary_json["suppressed"] == 1
        pickle = next(f for f in found if f.rule == "py.unsafe-deserialization")
        assert (pickle.path, pickle.line, pickle.snippet.strip()) == ("app/store.py", 6, "return pickle.loads(blob)")
        assert pickle.fingerprint and pickle.impact_json.get("exposure") == "internal"

    async def test_the_most_severe_come_first(self, db_session, project) -> None:
        kb = await _reading(db_session, project, FILES)
        _, found = await _run(db_session, project, kb)
        order = ["critical", "high", "medium", "low", "info"]
        ranks = [order.index(f.severity) for f in sorted(found, key=lambda f: f.id)]
        assert ranks == sorted(ranks)

    async def test_only_the_areas_asked_for(self, db_session, project) -> None:
        kb = await _reading(db_session, project, FILES)
        run, found = await _run(db_session, project, kb, areas=["config"])
        assert {f.area for f in found} == {"config"}
        assert [c["id"] for c in run.summary_json["checks"]] == ["deploy"]

    async def test_a_scope_of_paths(self, db_session, project) -> None:
        kb = await _reading(db_session, project, FILES)
        _, found = await _run(db_session, project, kb, scope={"kind": "paths", "paths": ["app"]})
        assert {f.path for f in found} == {"app/store.py"}


class TestAcrossRuns:
    async def test_new_and_fixed_against_the_run_before(self, db_session, project) -> None:
        first = await _reading(db_session, project, FILES)
        await _run(db_session, project, first)
        # The Dockerfile gets a user and a tag; a line is added above the pickle call.
        later = {**FILES, "Dockerfile": "FROM python:3.12\nUSER app\n", "app/store.py": "# a new first line\n" + APP}
        second = await _reading(db_session, project, later)
        run, found = await _run(db_session, project, second)
        pickle = next(f for f in found if f.rule == "py.unsafe-deserialization")
        assert pickle.line == 7 and not pickle.is_new  # moved, still the same finding
        assert run.summary_json["fixed"] == 3  # root, the unpinned image, and the COPY that went
        assert run.summary_json["new"] == 0

    async def test_a_dismissal_holds_on_the_next_run(self, db_session, project, user) -> None:
        kb = await _reading(db_session, project, FILES)
        _, found = await _run(db_session, project, kb)
        swallowed = next(f for f in found if f.rule == "py.swallowed-exception")
        service = QAService(db_session)
        await service.set_state(project.id, swallowed.fingerprint, "dismissed", "Callers handle None.", user)
        run, again = await _run(db_session, project, kb)
        assert swallowed.fingerprint in {f.fingerprint for f in again}
        assert run.summary_json["open"] == run.summary_json["total"] - 1
        states = await service.states(project.id)
        assert states[swallowed.fingerprint].reason == "Callers handle None."
        await service.set_state(project.id, swallowed.fingerprint, "open", "", user)
        assert swallowed.fingerprint not in await service.states(project.id)

    async def test_the_code_around_a_finding_is_shown_with_secrets_masked(self, db_session, project) -> None:
        kb = await _reading(db_session, project, {"app/conf.py": 'API_KEY = "a8Fk3LmQ9zX2pR7vWq1"\n'})
        _, found = await _run(db_session, project, kb, areas=["leakage"])
        leak = next(f for f in found if f.rule == "leak.credential-assignment")
        assert "a8Fk3LmQ9zX2pR7vWq1" not in leak.snippet
        detail, context = await QAService(db_session).finding(project.id, leak.id)
        assert context and all("a8Fk3LmQ9zX2pR7vWq1" not in text for _, text in context)
