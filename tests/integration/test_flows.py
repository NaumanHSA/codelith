"""
Flows: from a way into the code to the data it reaches, through the calls the reading
recorded. A three-step request — route → service → data access — read for real.
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
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.diagrams import request_flow
from codelith.knowledge.flows import FlowService
from codelith.knowledge.graph import build_code_graph
from codelith.knowledge.tools import TOOL_NAMES, CodebaseTools
from codelith.memory import get_graph_store
from codelith.memory.code_graph import GraphScope
from codelith.models.job import Job
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
        "ingestion_result": {"commit_sha": "f10f" * 10},
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
    await repos.bases.finish_build(state["kb_id"], status=KBStatus.READY)
    await db_session.commit()
    return await repos.bases.get_by_id(state["kb_id"])


class TestAFlow:
    async def test_a_route_is_followed_to_the_data(self, db_session, kb) -> None:
        flow = await FlowService(db_session, kb).find("POST /orders")
        assert flow is not None
        names = [flow.steps[i].qname for i in flow.chain]
        assert names == ["create_order", "place", "save"]
        assert flow.ends == "data"
        assert flow.steps[flow.chain[-1]].path == "app/data/store.py"

    async def test_it_is_found_by_handler_and_by_file(self, db_session, kb) -> None:
        service = FlowService(db_session, kb)
        assert (await service.find("create_order")).name == "POST /orders"
        assert (await service.find("routes.py")).name == "POST /orders"
        assert await service.find("nothing like it") is None

    async def test_the_brief_reads_top_to_bottom(self, db_session, kb) -> None:
        flow = await FlowService(db_session, kb).find("POST /orders")
        text = flow.brief()
        assert text.splitlines()[0].startswith("POST /orders — route")
        assert "reads or writes data" in text
        assert text.index("create_order") < text.index("place") < text.index("save")

    async def test_it_draws_as_a_diagram(self, db_session, kb) -> None:
        flow = await FlowService(db_session, kb).find("POST /orders")
        chain = [{"qname": flow.steps[i].qname, "path": flow.steps[i].path, "part": None} for i in flow.chain]
        source = request_flow(flow.name, chain, flow.ends)
        assert source and "->" in source and "save" in source


class TestTheTool:
    async def test_trace_flow_is_offered_to_agents_and_to_ask(self, db_session, kb) -> None:
        assert "trace_flow" in TOOL_NAMES
        tools = CodebaseTools(db_session, kb.id, kb.project_id)
        listing, _ = await tools.run("trace_flow", {})
        assert "POST /orders" in listing
        text, evidence = await tools.run("trace_flow", {"entry": "POST /orders"})
        assert "save" in text and evidence and evidence[0].title == "flow of POST /orders"
        missing, _ = await tools.run("trace_flow", {"entry": "DELETE /nowhere"})
        assert "No route" in missing


class TestOverHttp:
    async def test_list_and_one(self, db_session, kb, client) -> None:
        from codelith.core.security import create_access_token
        from codelith.models.user import User

        project = await db_session.get(Project, kb.project_id)
        user = User(
            org_id=project.org_id, email=f"f-{uuid.uuid4().hex[:8]}@example.com", password_hash="x",
            full_name="F", role="manager", is_active=True,
        )
        db_session.add(user)
        await db_session.flush()
        headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

        listed = (await client.get(f"/api/v1/projects/{kb.project_id}/flows", headers=headers)).json()
        (row,) = [f for f in listed["flows"] if f["name"] == "POST /orders"]
        assert row["ends"] == "data" and row["chain"] == 3

        one = await client.get(f"/api/v1/projects/{kb.project_id}/flows/{row['id']}", headers=headers)
        assert one.status_code == 200
        body = one.json()
        assert [body["all_steps"][i]["qname"] for i in body["chain_steps"]] == ["create_order", "place", "save"]
        assert body["diagram"] and "save" in body["brief"]


class TestAsk:
    async def test_a_question_naming_a_route_gets_its_flow(self, db_session, kb) -> None:
        from codelith.knowledge.questions import EvidenceBundle, QuestionPlan, QuestionRouter

        router = QuestionRouter(db_session, kb.id, kb.project_id, use_llm=False)
        bundle = EvidenceBundle(plan=QuestionPlan(question="What happens when somebody calls POST /orders?"))
        await router._add_flows(bundle, bundle.plan.question)
        assert [e.title for e in bundle.items] == ["flow of POST /orders"]

        quiet = EvidenceBundle(plan=QuestionPlan(question="How is configuration loaded?"))
        await router._add_flows(quiet, quiet.plan.question)
        assert quiet.items == []
