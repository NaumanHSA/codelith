"""
The tour: stops built from a reading, in the order a request meets the code, each
naming the parts to open, the files to light and — for the request — the flow to play.
A small shop read for real: a route, the service it calls, the store it writes.
"""

from __future__ import annotations

import textwrap
import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.agents.analysis import StructuredExtractorAgent
from codelith.apps import APPS_BY_ID
from codelith.apps.tour import TourService
from codelith.apps.tour.service import _sentences
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.ingestion.parsers.code_parser import ParsedCodebase, ParsedFile
from codelith.knowledge.builder import SourceFile
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.flows import FlowService
from codelith.knowledge.graph import build_code_graph
from codelith.memory import get_graph_store
from codelith.memory.code_graph import GraphScope
from codelith.models.job import Job
from codelith.models.knowledge import KBNarrative
from codelith.models.organization import Organization
from codelith.models.project import Project

SOURCES = {
    "app/web/routes.py": textwrap.dedent(
        '''
        from fastapi import APIRouter
        from app.services.orders import place

        router = APIRouter()

        @router.post("/orders")
        async def create_order(body: dict):
            return place(body)
        '''
    ),
    "app/services/orders.py": textwrap.dedent(
        '''
        from app.data.store import save


        def place(order: dict) -> dict:
            return save(order)
        '''
    ),
    "app/data/store.py": textwrap.dedent(
        '''
        from sqlalchemy import create_engine

        engine = create_engine("sqlite:///shop.db")


        def save(order):
            return order
        '''
    ),
}

OVERVIEW = (
    "Shop takes orders over HTTP and keeps them in a database. It is small on purpose.\n\n"
    "## More\n\nNot part of the tour."
)


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
        "ingestion_result": {"commit_sha": "70a7" * 10},
        "api_specs": [],
        "infra_context": [],
    }
    state.update(await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state))
    repos = KnowledgeRepositories.for_session(db_session)
    modules = await repos.modules.list_by_kb(state["kb_id"], include_tests=True)
    graph = build_code_graph(
        [SourceFile(path=p, content=c, language="python") for p, c in SOURCES.items()],
        module_roles={m.path: m.role for m in modules},
    )
    async with get_graph_store(db_session) as store:
        await store.write(GraphScope(project_id=project.id, kb_id=state["kb_id"], commit_sha=state["commit_sha"]), graph)
    db_session.add(KBNarrative(kb_id=state["kb_id"], topic="overview", content_md=OVERVIEW, source_refs_json={}))
    await repos.bases.finish_build(state["kb_id"], status=KBStatus.READY)
    await db_session.commit()
    return await repos.bases.get_by_id(state["kb_id"])


class TestTheStops:
    async def test_it_starts_with_what_the_code_is_and_ends_with_where_to_go(self, db_session, kb) -> None:
        tour = await TourService(db_session, kb).build()
        ids = [s.id for s in tour.stops]
        assert ids[0] == "start" and ids[-1] == "next"
        assert ids.index("layout") < ids.index("entry") < ids.index("flow")
        start = tour.stops[0]
        assert "Shop takes orders over HTTP" in start.body
        assert "Not part of the tour" not in start.body
        assert "3 files" in start.body

    async def test_the_request_is_a_real_flow_followed_to_its_data(self, db_session, kb) -> None:
        tour = await TourService(db_session, kb).build()
        stop = next(s for s in tour.stops if s.id == "flow")
        flow = await FlowService(db_session, kb).find(stop.flow)
        assert flow is not None and flow.name == "POST /orders"
        assert [f.path for f in stop.files] == ["app/web/routes.py", "app/services/orders.py", "app/data/store.py"]
        assert "`create_order`" in stop.body and "`save`" in stop.body
        assert "reads or writes data" in stop.body

    async def test_where_work_comes_in_names_the_file_it_is_declared_in(self, db_session, kb) -> None:
        tour = await TourService(db_session, kb).build()
        entry = next(s for s in tour.stops if s.id == "entry")
        assert "1 route" in entry.body
        assert entry.files[0].path == "app/web/routes.py"

    async def test_every_file_it_names_exists_in_the_reading(self, db_session, kb) -> None:
        tour = await TourService(db_session, kb).build()
        for stop in tour.stops:
            for f in stop.files:
                assert f.path in SOURCES, (stop.id, f.path)

    async def test_it_exports_as_a_document(self, db_session, kb) -> None:
        tour = await TourService(db_session, kb).build()
        text = tour.markdown()
        assert text.startswith("# A tour of shop\n")
        assert "`70a770a7`" in text
        assert "## 1. What shop is" in text
        assert "- `app/web/routes.py`" in text


class TestItIsAnApp:
    def test_it_is_registered_and_opens_on_the_graph(self) -> None:
        app = APPS_BY_ID["tour"]
        assert app.built and "{id}" in app.route and "tour=1" in app.route


class TestSentences:
    def test_a_paragraph_that_only_introduces_a_list_is_skipped(self) -> None:
        text = "The models cover:\n\n- users\n- orders\n\nOrders belong to users. Each has a total."
        assert _sentences(text, 2) == "Orders belong to users. Each has a total."

    def test_sentences_about_the_source_material_are_left_out(self) -> None:
        text = "The inventory does not show field names. Orders belong to users."
        assert _sentences(text, 2) == "Orders belong to users."

    def test_it_stops_at_the_limit_on_a_sentence(self) -> None:
        text = "One short sentence. " + "Two " * 200 + "end."
        assert _sentences(text, 3, limit=60) == "One short sentence."
