"""
Requests followed through a real reading: a shop with an open write route, a guarded
read, a sign-in that is public on purpose, and a search whose query is pasted into SQL
two calls down.
"""

from __future__ import annotations

import json
import textwrap
import uuid

import pytest_asyncio
from sqlalchemy import select

from codelith.agents.analysis import StructuredExtractorAgent
from codelith.apps.qa.service import QAService
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.ingestion.parsers.code_parser import ParsedCodebase, ParsedFile
from codelith.knowledge.builder import SourceFile
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.graph import build_code_graph
from codelith.memory import get_graph_store
from codelith.memory.code_graph import GraphScope
from codelith.models.job import Job
from codelith.models.organization import Organization
from codelith.models.project import Project
from codelith.models.qa import QAFinding, QARun

SOURCES = {
    "app/deps.py": textwrap.dedent(
        """
        from typing import Annotated
        from fastapi import Depends


        def get_current_user():
            return None


        CurrentUser = Annotated[dict, Depends(get_current_user)]
        """
    ),
    "app/web/routes.py": textwrap.dedent(
        """
        from fastapi import APIRouter
        from app.deps import CurrentUser
        from app.services.orders import place, find, search, sign_in

        router = APIRouter()


        @router.post("/orders")
        async def create_order(body: dict):
            return place(body)


        @router.get("/orders/{oid}")
        async def read_order(oid: str, user: CurrentUser):
            return find(oid)


        @router.post("/login")
        async def login(body: dict):
            return sign_in(body)


        @router.get("/search")
        async def search_orders(q: str):
            return search(q)
        """
    ),
    "app/services/orders.py": textwrap.dedent(
        """
        from app.data.store import save, load, query, check


        def place(order):
            return save(order)


        def find(oid):
            return load(oid)


        def search(term):
            return query(term)


        def sign_in(body):
            return check(body)
        """
    ),
    "app/data/store.py": textwrap.dedent(
        """
        from sqlalchemy import create_engine

        engine = create_engine("sqlite:///shop.db")


        def save(order):
            return order


        def load(oid):
            return oid


        def query(term):
            with engine.connect() as conn:
                return conn.execute(f"SELECT * FROM orders WHERE name = '{term}'")


        def check(body):
            return body


        def refund(order):
            amount = order["total"]
            if amount > 0:
                order["refunded"] = amount
            return order
        """
    ),
    "app/schemas.py": textwrap.dedent(
        """
        from pydantic import BaseModel


        class UserOut(BaseModel):
            email: str
            password_hash: str


        class TokenOut(BaseModel):
            access_token: str
        """
    ),
}


@pytest_asyncio.fixture
async def kb(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-qf-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="shop", slug=f"shop-qf-{tag}")
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
        "ingestion_result": {"commit_sha": uuid.uuid4().hex},
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


async def _run(db_session, kb) -> tuple[QARun, list[QAFinding]]:
    run = QARun(project_id=kb.project_id, kb_id=kb.id, areas_json=["security", "leakage"], scope_json={"kind": "all"})
    db_session.add(run)
    await db_session.commit()
    await QAService(db_session).execute(run.id)
    return run, list((await db_session.execute(select(QAFinding).where(QAFinding.run_id == run.id))).scalars())


class TestRoutes:
    async def test_open_routes_that_reach_data_and_no_others(self, db_session, kb) -> None:
        _, found = await _run(db_session, kb)
        open_routes = {f.title: f.severity for f in found if f.rule == "security.route-unguarded"}
        assert open_routes == {
            "`POST /orders` changes data with no auth step": "high",
            "`GET /search` reads data with no auth step": "medium",
        }

    async def test_request_data_reaching_sql_joins_the_line_rule(self, db_session, kb) -> None:
        _, found = await _run(db_session, kb)
        sql = [f for f in found if f.path == "app/data/store.py" and f.area == "security"]
        assert len(sql) == 1, [(f.rule, f.line) for f in sql]
        f = sql[0]
        assert f.rule == "py.sql-built" and f.severity == "critical"
        assert f.evidence_json["raised_from"] == "high"
        assert f.impact_json["chain"] == ["GET /search", "search_orders", "search", "query"]
        assert f.impact_json["exposure"] == "public"

    async def test_a_secret_in_a_response_model_but_not_a_token_in_the_token_model(self, db_session, kb) -> None:
        _, found = await _run(db_session, kb)
        assert [f.title for f in found if f.rule == "leak.response-secret-field"] == ["`UserOut` sends `password_hash` to the client"]


class TestThoroughReview:
    async def test_only_anchored_confirmed_new_claims_are_kept(self, db_session, kb, monkeypatch) -> None:
        from codelith.llm import client as llm

        calls: list[str] = []
        at = SOURCES["app/data/store.py"].splitlines().index("    if amount > 0:") + 1

        async def fake(messages, spec=None, **_kw):
            system = messages[0]["content"]
            calls.append("review" if "You review code" in system else "confirm")
            if "You review code" in system:
                if "Function: refund" not in messages[1]["content"]:
                    return '{"issues": []}'
                issues = [
                    {"area": "errors", "severity": "medium", "line": at, "quote": "if amount > 0:",
                     "title": "keep: a refund is never recorded as paid out", "why": "Nothing is written.", "fix": "Write it."},
                    {"area": "errors", "severity": "high", "line": at, "quote": "this line is not there",
                     "title": "invented", "why": "x", "fix": "y"},
                    {"area": "breaks", "severity": "low", "line": at, "quote": "if amount > 0:",
                     "title": "refuted claim", "why": "x", "fix": "y"},
                ]
                return json.dumps({"issues": issues})
            verdict = "real" if "keep:" in messages[1]["content"] else "not_real"
            return json.dumps({"verdict": verdict, "reason": "checked"})

        monkeypatch.setattr(llm, "chat_completion", fake)
        run = QARun(project_id=kb.project_id, kb_id=kb.id, areas_json=["errors", "breaks"], scope_json={"kind": "all"}, depth="thorough")
        db_session.add(run)
        await db_session.commit()
        await QAService(db_session).execute(run.id)
        found = list((await db_session.execute(select(QAFinding).where(QAFinding.run_id == run.id))).scalars())
        reviewed = [f for f in found if f.source == "model"]
        assert [(f.rule, f.title, f.confidence, f.line) for f in reviewed] == [
            ("review.errors", "keep: a refund is never recorded as paid out", "suspected", at)
        ]
        note = next(n for n in run.summary_json["notes"] if n.startswith("The model reviewed"))
        assert "3 claim(s), 1 dropped because the quoted line was not where it said, 1 dropped on a second look, 1 kept" in note
        assert calls.count("confirm") == 2

    async def test_a_quick_run_never_calls_the_model(self, db_session, kb, monkeypatch) -> None:
        from codelith.llm import client as llm

        async def boom(*_a, **_kw):
            raise AssertionError("a quick run called the model")

        monkeypatch.setattr(llm, "chat_completion", boom)
        run, _ = await _run(db_session, kb)
        assert run.status == "completed"
