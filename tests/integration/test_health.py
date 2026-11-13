"""
Hotspots and the timeline on a small shop read for real: a route, the service it
calls, the store it writes, and a helper both of them import.
"""

from __future__ import annotations

import textwrap
import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.agents.analysis import StructuredExtractorAgent
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.ingestion.parsers.code_parser import ParsedCodebase, ParsedFile
from codelith.knowledge.builder import SourceFile
from codelith.knowledge.churn import Churn
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.graph import build_code_graph
from codelith.knowledge.hotspots import MIN_RECENT_COMMITS, HotspotService, score
from codelith.knowledge.timeline import TimelineService
from codelith.memory import get_graph_store
from codelith.memory.code_graph import GraphScope
from codelith.models.job import Job
from codelith.models.organization import Organization
from codelith.models.project import Project

SOURCES = {
    "app/web/routes.py": textwrap.dedent(
        '''
        from app.services.orders import place
        from app.util.text import clean


        def create_order(body):
            return place(clean(body))
        '''
    ),
    "app/services/orders.py": textwrap.dedent(
        '''
        from app.util.text import clean


        def place(order):
            return clean(order)
        '''
    ),
    "app/util/text.py": textwrap.dedent(
        '''
        def clean(value):
            return value
        '''
    ),
}


@pytest_asyncio.fixture
async def kb(db_session: AsyncSession):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="shop", slug=f"shop-{tag}")
    db_session.add(project)
    await db_session.flush()
    job = Job(project_id=project.id, job_type="analysis", status="running", config_json={})
    db_session.add(job)
    await db_session.flush()

    codebase = ParsedCodebase(root_path="/tmp/shop")
    codebase.files = [ParsedFile(path=p, language="python", content=c, size_bytes=len(c)) for p, c in SOURCES.items()]
    state = {
        "project": project,
        "job": job,
        "codebase": codebase,
        "ingestion_result": {"commit_sha": "4ea1" * 10},
        "api_specs": [],
        "infra_context": [],
    }
    state.update(await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state))
    repos = KnowledgeRepositories.for_session(db_session)
    graph = build_code_graph([SourceFile(path=p, content=c, language="python") for p, c in SOURCES.items()])
    async with get_graph_store(db_session) as store:
        await store.write(GraphScope(project_id=project.id, kb_id=state["kb_id"], commit_sha=state["commit_sha"]), graph)
    await repos.bases.finish_build(state["kb_id"], status=KBStatus.READY)
    await db_session.commit()
    return await repos.bases.get_by_id(state["kb_id"])


def _churn(recent: dict[str, int], total: dict[str, int] | None = None, recent_commits: int = 20) -> Churn:
    return Churn(
        recent=recent,
        total=total or recent,
        commits=max(recent_commits, sum((total or recent).values())),
        recent_commits=recent_commits,
        since="2026-01-01",
    )


class TestHotspots:
    async def test_a_reading_without_history_says_so(self, db_session, kb) -> None:
        report = await HotspotService(db_session, kb).rank()
        assert not report.available and "history" in report.reason

    async def test_reach_lifts_a_file_that_changes_as_often(self, db_session, kb) -> None:
        # Both changed three times; the helper is imported by two files, the route by none.
        churn = _churn({"app/util/text.py": 3, "app/web/routes.py": 3})
        report = await HotspotService(db_session, kb).rank(churn=churn)
        assert [h.path for h in report.hotspots] == ["app/util/text.py", "app/web/routes.py"]
        top = report.hotspots[0]
        assert top.reach == 2 and top.tests == 0 and top.level == "hot"
        assert top.score == score(3, 2, tested=False)

    async def test_a_file_that_never_changed_is_not_a_hotspot(self, db_session, kb) -> None:
        report = await HotspotService(db_session, kb).rank(churn=_churn({"app/web/routes.py": 1}))
        assert [h.path for h in report.hotspots] == ["app/web/routes.py"]

    async def test_a_quiet_window_falls_back_to_the_whole_history(self, db_session, kb) -> None:
        churn = _churn({}, total={"app/services/orders.py": 7}, recent_commits=MIN_RECENT_COMMITS - 1)
        report = await HotspotService(db_session, kb).rank(churn=churn)
        assert report.window == "all"
        assert [(h.path, h.changes) for h in report.hotspots] == [("app/services/orders.py", 7)]

    async def test_history_kept_with_the_reading_is_used(self, db_session, kb) -> None:
        kb.churn_json = _churn({"app/web/routes.py": 2}).to_json()
        await db_session.commit()
        report = await HotspotService(db_session, kb).rank()
        assert report.available and report.hotspots[0].path == "app/web/routes.py"


class TestTimeline:
    async def test_a_reading_is_counted(self, db_session, kb) -> None:
        readings = await TimelineService(db_session, kb.project_id).readings()
        assert len(readings) == 1
        r = readings[0]
        assert r.kb_id == kb.id and r.commit == kb.commit_sha
        assert r.files == 3
        assert sum(p.files for p in r.parts) == 3
        assert r.loc > 0
