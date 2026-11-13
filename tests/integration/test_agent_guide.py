"""
The instruction file agents read first, written from the reading: the house-style
recipes (`how_to`), the file with its markers, and the merge that leaves hand-written
text alone. A small shop read for real: two route files wired into one app, settings
read in one place, models, and tests.
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
from codelith.knowledge.graph import build_code_graph
from codelith.knowledge.guide import BEGIN, END, RECIPE_IDS, GuideService, merge
from codelith.knowledge.tools import TOOL_NAMES, CodebaseTools
from codelith.memory import get_graph_store
from codelith.memory.code_graph import GraphScope
from codelith.models.job import Job
from codelith.models.knowledge import KBNarrative
from codelith.models.organization import Organization
from codelith.models.project import Project

SOURCES = {
    "app/main.py": textwrap.dedent(
        '''
        from fastapi import FastAPI
        from app.web import orders, users

        app = FastAPI()
        app.include_router(orders.router)
        app.include_router(users.router)
        '''
    ),
    "app/web/orders.py": textwrap.dedent(
        '''
        from fastapi import APIRouter
        from app.models import Order

        router = APIRouter()

        @router.post("/orders")
        async def create_order(body: dict) -> Order:
            return Order(**body)

        @router.get("/orders/{order_id}")
        async def read_order(order_id: int) -> Order:
            return Order(id=order_id)
        '''
    ),
    "app/web/users.py": textwrap.dedent(
        '''
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/users")
        async def list_users() -> list:
            return []
        '''
    ),
    "app/config.py": textwrap.dedent(
        '''
        import os

        DATABASE_URL = os.getenv("SHOP_DATABASE_URL", "sqlite:///shop.db")
        SECRET = os.environ.get("SHOP_SECRET", "dev")
        '''
    ),
    "app/models.py": textwrap.dedent(
        '''
        from dataclasses import dataclass


        @dataclass
        class Order:
            id: int = 0
            total: float = 0.0
        '''
    ),
    "tests/test_orders.py": textwrap.dedent(
        '''
        from app.web.orders import create_order


        def test_create_order():
            assert create_order
        '''
    ),
}

OVERVIEW = (
    "Shop is a small order service. It takes orders over HTTP and keeps them in a database.\n\n"
    "## Parts\n\n"
    "- web\n- models\n\n"
    "Requests come in through FastAPI routers that the app mounts at start."
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
        "ingestion_result": {"commit_sha": "9a1d" * 10},
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


class TestRecipes:
    async def test_routes_say_where_they_live_and_where_they_are_wired(self, db_session, kb) -> None:
        recipe = await GuideService(db_session, kb).recipe("route")
        assert recipe is not None
        text = recipe.text()
        assert "3 routes are declared under `app/web/`" in text
        assert "most in `app/web/orders.py`" in text
        # The example has a line, so an agent can open it.
        assert "`app/web/orders.py:" in text
        assert "registered in `app/main.py`, which imports 2 of them" in text

    async def test_settings_point_at_the_one_place_they_are_read(self, db_session, kb) -> None:
        recipe = await GuideService(db_session, kb).recipe("setting")
        assert recipe is not None
        text = recipe.text()
        assert "`app/config.py`" in text
        assert "SHOP_DATABASE_URL" in text

    async def test_models_and_tests_are_found_from_the_layout(self, db_session, kb) -> None:
        service = GuideService(db_session, kb)
        model = await service.recipe("model")
        assert model is not None and "`app/models.py`" in model.text()
        test = await service.recipe("test")
        assert test is not None
        assert "`tests/`" in test.text() and "`test_*.py`" in test.text()

    async def test_a_kind_the_code_does_not_have_is_no_recipe(self, db_session, kb) -> None:
        assert await GuideService(db_session, kb).recipe("scheduled_job") is None

    async def test_how_to_serves_them_to_agents(self, db_session, kb) -> None:
        assert "how_to" in TOOL_NAMES
        tools = CodebaseTools(db_session, kb.id, kb.project_id)
        text, evidence = await tools.run("how_to", {"kind": "route"})
        assert text.startswith("Add an API route:") and evidence[0].title == "how to: route"
        missing, _ = await tools.run("how_to", {"kind": "event"})
        assert "has no events to learn from" in missing
        wrong, _ = await tools.run("how_to", {"kind": "spaceship"})
        assert all(rid in wrong for rid in RECIPE_IDS)


class TestTheFile:
    async def test_it_is_wrapped_in_markers_and_dated(self, db_session, kb) -> None:
        text = await GuideService(db_session, kb).markdown()
        assert text.startswith(BEGIN) and text.rstrip().endswith(END)
        assert "reading of shop at 9a1d9a1d" in text

    async def test_it_opens_on_the_overview_without_its_lists(self, db_session, kb) -> None:
        text = await GuideService(db_session, kb).markdown()
        about = text.split("## About this codebase", 1)[1].split("## ", 1)[0]
        assert "Shop is a small order service." in about
        assert "Requests come in through FastAPI routers" in about
        assert "- web" not in about

    async def test_it_has_the_layout_the_style_and_the_tools(self, db_session, kb) -> None:
        text = await GuideService(db_session, kb).markdown()
        for heading in ("## How the code is laid out", "## How things are done here", "## Working with Codelith"):
            assert heading in text
        assert "**Add an API route.**" in text
        assert "Imports run down that list" in text
        for tool in ("before_edit", "trace_flow", "how_to", "review_changes"):
            assert f"`{tool}`" in text


class TestMerge:
    SECTION = f"{BEGIN}\nnew\n{END}\n"

    def test_a_new_file_gets_a_title(self) -> None:
        assert merge(None, self.SECTION, "shop") == f"# shop\n\n{self.SECTION}"

    def test_only_its_own_section_is_replaced(self) -> None:
        existing = f"# Mine\n\nWritten by hand.\n\n{BEGIN}\nold\n{END}\n\n## Also mine\n\nKeep this.\n"
        merged = merge(existing, self.SECTION, "shop")
        assert "old" not in merged and "\nnew\n" in merged
        assert merged.startswith("# Mine\n\nWritten by hand.\n\n")
        assert merged.endswith("## Also mine\n\nKeep this.\n")
        assert merged.count(BEGIN) == 1 and merged.count(END) == 1

    def test_a_file_without_markers_keeps_everything_and_gains_the_section(self) -> None:
        existing = "# Mine\n\nWritten by hand.\n"
        merged = merge(existing, self.SECTION, "shop")
        assert merged == "# Mine\n\nWritten by hand.\n\n" + self.SECTION

    def test_merging_twice_changes_nothing_more(self) -> None:
        once = merge("# Mine\n", self.SECTION, "shop")
        assert merge(once, self.SECTION, "shop") == once
