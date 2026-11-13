"""
Reviewing a change against what the knowledge base knows.

A four-part codebase — web calls orders, orders store through storage and format with
helpers, a test drives orders — is read for real (extraction and the code graph, no
model), and each finding a review can make is provoked by a change written by hand.

The columns are fixed in these tests (web, core, helpers, data) so they test the
review's rules; how columns are worked out is tested on its own below.
"""

from __future__ import annotations

import textwrap
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.agents.analysis import StructuredExtractorAgent
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.ingestion.parsers.code_parser import ParsedCodebase, ParsedFile
from codelith.knowledge import review as review_mod
from codelith.knowledge.atlas import Atlas, AtlasComponent, AtlasNode
from codelith.knowledge.builder import SourceFile
from codelith.knowledge.changes import ChangedFile, ChangeSet
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.graph import build_code_graph
from codelith.knowledge.review import ReviewService
from codelith.knowledge.shape import component_tiers
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
        from app.helpers.fmt import fmt


        def place(order: dict) -> dict:
            saved = save(order)
            return {"id": fmt(saved)}


        def cancel(order_id: int) -> None:
            return None
        '''
    ),
    "app/data/store.py": "def save(x):\n    return x\n",
    "app/helpers/fmt.py": "def fmt(x):\n    return str(x)\n",
    "tests/test_orders.py": "from app.services.orders import place\n\n\ndef test_place():\n    assert place({})\n",
}

PARTS = {"app/web": "Web", "app/services": "Orders", "app/data": "Storage", "app/helpers": "Helpers"}
COLUMNS = {"Web": 0, "Orders": 1, "Helpers": 2, "Storage": 3}


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
    codebase.files = [
        ParsedFile(path=p, language="python", content=c, size_bytes=len(c)) for p, c in SOURCES.items()
    ]
    state = {
        "project": project,
        "job": job,
        "codebase": codebase,
        "ingestion_result": {"commit_sha": "c0ffee00" * 5},
        "api_specs": [],
        "infra_context": [],
    }
    state.update(await StructuredExtractorAgent(db=db_session, job_id=job.id).run(state))

    repos = KnowledgeRepositories.for_session(db_session)
    modules = await repos.modules.list_by_kb(state["kb_id"], include_tests=True)
    # The code graph, written through this session (the agent opens its own, which a
    # test's open transaction would lock out).
    graph = build_code_graph(
        [SourceFile(path=p, content=c, language="python") for p, c in SOURCES.items()],
        module_roles={m.path: m.role for m in modules},
    )
    async with get_graph_store(db_session) as store:
        await store.write(GraphScope(project_id=project.id, kb_id=state["kb_id"], commit_sha=state["commit_sha"]), graph)
    services = [
        {"name": PARTS[m.path], "description": "", "modules": [m.name]} for m in modules if m.path in PARTS
    ]
    await repos.bases.finish_build(state["kb_id"], status=KBStatus.READY, architecture={"services": services})
    await db_session.commit()
    return await repos.bases.get_by_id(state["kb_id"])


@pytest.fixture(autouse=True)
def fixed_columns(monkeypatch):
    real = review_mod.shape_of

    def fixed(atlas):
        shape = real(atlas)
        shape.tiers = [COLUMNS.get(c.name, -1) if shape.tiers[i] >= 0 else -1 for i, c in enumerate(atlas.components)]
        return shape

    monkeypatch.setattr(review_mod, "shape_of", fixed)


def edit(path: str, content: str, *, old: list[tuple[int, int]] = (), new: list[tuple[int, int]] = ()) -> ChangedFile:
    return ChangedFile(path=path, status="modified", old_ranges=list(old), new_ranges=list(new), content=content)


async def review(db, kb, *files: ChangedFile):
    return await ReviewService(db, kb).review(ChangeSet(base=kb.commit_sha, head=None, files=list(files)))


def kinds(report, severity=None):
    return [f.kind for f in report.findings if severity is None or f.severity == severity]


class TestWhatItTouches:
    async def test_names_the_functions_changed_and_the_tests_to_run(self, db_session, kb) -> None:
        changed = SOURCES["app/services/orders.py"].replace('return {"id": fmt(saved)}', 'return {"id": fmt(saved), "ok": True}')
        report = await review(db_session, kb, edit("app/services/orders.py", changed, old=[(8, 8)], new=[(8, 8)]))

        (impact,) = report.files
        assert impact.part == "Orders"
        assert "place" in " ".join(impact.symbols)
        assert "cancel" not in " ".join(impact.symbols)
        assert impact.reach >= 1  # the route and the test import it
        assert "tests/test_orders.py" in report.tests
        assert report.verdict in ("clear", "check")

    async def test_a_test_only_change_is_clear(self, db_session, kb) -> None:
        test = SOURCES["tests/test_orders.py"] + "\n\ndef test_more():\n    assert True\n"
        report = await review(db_session, kb, edit("tests/test_orders.py", test, new=[(6, 8)]))
        assert report.verdict == "clear"
        assert not kinds(report, "stop")


class TestTheShape:
    async def test_a_new_dependency_between_parts_is_worth_checking(self, db_session, kb) -> None:
        routes = "from app.helpers.fmt import fmt\n" + SOURCES["app/web/routes.py"]
        report = await review(db_session, kb, edit("app/web/routes.py", routes, new=[(1, 1)]))
        assert "new_dependency" in kinds(report, "warn")
        assert report.verdict == "check"
        (link,) = report.links
        assert link.kind == "new"

    async def test_an_import_against_the_columns_is_a_stop(self, db_session, kb) -> None:
        # Storage (data) reaching up into Helpers: Helpers never reaches Storage, so it
        # is not a loop, only the wrong way round.
        store = "from app.helpers.fmt import fmt\n\n\ndef save(x):\n    return fmt(x)\n"
        report = await review(db_session, kb, edit("app/data/store.py", store, old=[(1, 2)], new=[(1, 5)]))
        finding = next(f for f in report.findings if f.kind == "layering")
        assert finding.severity == "stop"
        assert finding.path == "app/data/store.py" and finding.line == 1
        assert report.verdict == "stop"

    async def test_a_new_loop_between_parts_is_a_stop(self, db_session, kb) -> None:
        # Orders already depends on Storage; Storage importing Orders closes the loop.
        store = "from app.services.orders import cancel\n\n\ndef save(x):\n    return x\n"
        report = await review(db_session, kb, edit("app/data/store.py", store, new=[(1, 1)]))
        assert "loop" in kinds(report, "stop")
        assert any(link.kind == "loop" for link in report.links)


class TestWhatItBreaks:
    async def test_deleting_a_file_others_still_import_is_a_stop(self, db_session, kb) -> None:
        gone = ChangedFile(path="app/helpers/fmt.py", status="deleted", old_ranges=[(1, 2)])
        report = await review(db_session, kb, gone)
        finding = next(f for f in report.findings if f.kind == "broken_import")
        assert finding.severity == "stop"
        assert "app/services/orders.py" in finding.message

    async def test_removing_a_route_is_said_and_adding_one_is_noted(self, db_session, kb) -> None:
        routes = SOURCES["app/web/routes.py"].replace('@router.post("/orders")', '@router.put("/orders/{order_id}")')
        report = await review(db_session, kb, edit("app/web/routes.py", routes, old=[(7, 7)], new=[(7, 7)]))
        assert any("POST /orders" in r for r in report.facts_removed)
        assert any("PUT /orders" in a for a in report.facts_added)
        assert "removed_route" in kinds(report, "warn")


class TestTheReport:
    async def test_the_brief_leads_with_the_verdict_and_names_files(self, db_session, kb) -> None:
        gone = ChangedFile(path="app/helpers/fmt.py", status="deleted", old_ranges=[(1, 2)])
        report = await review(db_session, kb, gone)
        text = report.brief()
        assert text.startswith("1 changed file")
        assert "Stop and look:" in text
        assert "app/helpers/fmt.py" in text

    async def test_it_is_kept_and_listed_over_http(self, db_session, kb, client) -> None:
        from codelith.core.security import create_access_token
        from codelith.models.user import User

        project = await db_session.get(Project, kb.project_id)
        user = User(
            org_id=project.org_id, email=f"r-{uuid.uuid4().hex[:8]}@example.com", password_hash="x",
            full_name="R", role="manager", is_active=True,
        )
        db_session.add(user)
        await db_session.flush()
        headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

        change = ChangeSet(
            base=kb.commit_sha, head=None, files=[ChangedFile(path="app/helpers/fmt.py", status="deleted")]
        )
        created = await client.post(
            f"/api/v1/projects/{kb.project_id}/reviews",
            json={"change": change.to_dict(), "source": "cli"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["verdict"] == "stop"
        assert "Stop and look" in body["report"]["brief"]

        listed = (await client.get(f"/api/v1/projects/{kb.project_id}/reviews", headers=headers)).json()
        assert listed["reviews"][0]["id"] == body["id"]
        assert listed["reviews"][0]["source"] == "cli"
        assert listed["can_review_working_copy"] is False  # read from nowhere on this machine

        working = await client.post(f"/api/v1/projects/{kb.project_id}/reviews", json={}, headers=headers)
        assert working.status_code == 422
        assert "codelith review" in working.json()["detail"]


class TestColumns:
    """How the columns are worked out, on a map built by hand."""

    def test_entry_core_helpers_and_data(self) -> None:
        components = [
            AtlasComponent("Web", "", "component"),
            AtlasComponent("Orders", "", "component"),
            AtlasComponent("Helpers", "", "component"),
            AtlasComponent("Storage", "", "component"),
        ]
        nodes = [
            AtlasNode("w", "w.py", "api", 0),
            AtlasNode("o", "o.py", "service", 1),
            AtlasNode("h", "h.py", "util", 2),
            AtlasNode("s", "s.py", "data", 3),
        ]
        # web → orders → (helpers, storage); helpers is leant on, storage is data.
        atlas = Atlas(commit=None, components=components, nodes=nodes, edges=[(0, 1), (1, 2), (1, 3)])
        assert component_tiers(atlas) == [0, 1, 2, 3]
