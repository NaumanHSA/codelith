"""
The atlas, built from tables analysis filled.

The unit tests pin which kind a file is. These pin the joins: that a file lands in the
component its module was assigned to, that files nobody placed are kept rather than
dropped, that facts become nodes linked from the file declaring them, and that one
file's call listing separates what it calls from what calls it.
"""

from __future__ import annotations

import uuid

import pytest

from codelith.knowledge.atlas import CONFIGURATION, OUTSIDE, UNMAPPED, AtlasService
from codelith.knowledge.constants import KBStatus
from codelith.models.graph import GraphCall, GraphFile, GraphImport, GraphSymbol
from codelith.models.knowledge import KBEntity, KBModule, KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project

ARCHITECTURE = {
    "services": [
        {"name": "HTTP API", "description": "Routes.", "modules": ["app.api"]},
        {"name": "Storage", "description": "Persistence.", "modules": ["app.store"]},
    ]
}


@pytest.fixture
async def kb(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-at-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="at", slug=f"at-{tag}")
    db_session.add(project)
    await db_session.flush()
    base = KnowledgeBase(
        project_id=project.id, commit_sha=tag, status=KBStatus.READY, architecture_json=ARCHITECTURE
    )
    db_session.add(base)
    await db_session.flush()

    key = {"project_id": project.id, "kb_id": base.id}
    for path, name, role, is_test in [
        ("app/api", "app.api", "service", False),
        ("app/store", "app.store", "service", False),
        ("app/misc", "app.misc", "service", False),
        ("tests", "tests", "test", True),
    ]:
        db_session.add(
            KBModule(kb_id=base.id, path=path, name=name, kind="package", role=role, is_test=is_test)
        )
    for path, module in [
        ("app/api/routes.py", "app/api"),
        ("app/store/db.py", "app/store"),
        ("app/misc/loop.py", "app/misc"),
        ("tests/test_routes.py", "tests"),
    ]:
        db_session.add(GraphFile(**key, path=path, module_key=module, language="python", loc=10))
    for src, dst in [
        ("app/api/routes.py", "app/store/db.py"),
        ("tests/test_routes.py", "app/api/routes.py"),
        ("app/api/routes.py", "app/api/routes.py"),  # a self-import is not an edge
    ]:
        db_session.add(GraphImport(**key, src=src, dst=dst))
    for kind, name, source, data in [
        ("route", "GET /items", "app/api/routes.py", {}),
        ("datastore", "SQLite", "app/store/db.py", {"engine": "sql"}),
        ("external_api", "api.example.com", "app/misc/loop.py", {"via": "url"}),
        ("config_file", ".env.example", ".env.example", {"purpose": "environment"}),
    ]:
        db_session.add(
            KBEntity(kb_id=base.id, kind=kind, name=name, source_path=source, data_json=data)
        )
    db_session.add_all(
        [
            GraphSymbol(**key, path="app/store/db.py", qname="save", name="save", kind="function", line=3),
            GraphSymbol(**key, path="app/store/db.py", qname="TIMEOUT", name="TIMEOUT", kind="constant", line=1),
            GraphCall(**key, src_path="app/api/routes.py", src_qname="get_items", dst_path="app/store/db.py", dst_qname="save"),
            GraphCall(**key, src_path="app/store/db.py", src_qname="save", dst_path="app/misc/loop.py", dst_qname="tick"),
        ]
    )
    await db_session.flush()
    return base


def _by_path(atlas):
    return {n.path: n for n in atlas.nodes}


@pytest.mark.asyncio
async def test_files_take_their_kind_and_their_component(db_session, kb) -> None:
    atlas = await AtlasService(db_session, kb).build()
    nodes = _by_path(atlas)
    names = [c.name for c in atlas.components]

    assert nodes["app/api/routes.py"].kind == "api"
    assert names[nodes["app/api/routes.py"].component] == "HTTP API"
    assert nodes["app/store/db.py"].kind == "data"
    assert names[nodes["app/store/db.py"].component] == "Storage"
    assert nodes["tests/test_routes.py"].kind == "test"


@pytest.mark.asyncio
async def test_a_file_nothing_ties_to_a_part_is_kept_in_other_and_says_why(db_session, kb) -> None:
    atlas = await AtlasService(db_session, kb).build()
    loop = _by_path(atlas)["app/misc/loop.py"]
    assert atlas.components[loop.component].name == UNMAPPED == "Other"
    assert atlas.components[loop.component].group == "other"
    assert loop.why and loop.why.startswith("Nothing ties it")


@pytest.mark.asyncio
async def test_a_test_nobody_placed_goes_to_the_tests(db_session, kb) -> None:
    atlas = await AtlasService(db_session, kb).build()
    test = _by_path(atlas)["tests/test_routes.py"]
    assert (atlas.components[test.component].name, atlas.components[test.component].group) == ("Tests", "tests")


@pytest.mark.asyncio
async def test_a_file_analysis_placed_says_so(db_session, kb) -> None:
    atlas = await AtlasService(db_session, kb).build()
    assert _by_path(atlas)["app/api/routes.py"].why == "Analysis listed it in this part."


@pytest.mark.asyncio
async def test_facts_become_nodes_linked_from_the_file_declaring_them(db_session, kb) -> None:
    atlas = await AtlasService(db_session, kb).build()
    nodes = _by_path(atlas)
    index = {n.path: i for i, n in enumerate(atlas.nodes)}

    store, outside, env = nodes["SQLite"], nodes["api.example.com"], nodes[".env.example"]
    assert (store.kind, store.fact, store.detail) == ("store", "datastore", "sql")
    assert outside.kind == "external"
    assert env.kind == "env"
    assert atlas.components[store.component].name == OUTSIDE
    assert atlas.components[env.component].name == CONFIGURATION

    assert (index["app/store/db.py"], index["SQLite"]) in atlas.edges
    assert (index["app/misc/loop.py"], index["api.example.com"]) in atlas.edges


@pytest.mark.asyncio
async def test_imports_are_edges_and_a_self_import_is_not(db_session, kb) -> None:
    atlas = await AtlasService(db_session, kb).build()
    index = {n.path: i for i, n in enumerate(atlas.nodes)}
    assert (index["app/api/routes.py"], index["app/store/db.py"]) in atlas.edges
    assert (index["tests/test_routes.py"], index["app/api/routes.py"]) in atlas.edges
    assert all(a != b for a, b in atlas.edges)
    assert atlas.kinds["api"] == 1


@pytest.mark.asyncio
async def test_one_file_from_the_inside(db_session, kb) -> None:
    calls = await AtlasService(db_session, kb).calls("app/store/db.py")
    assert [s["name"] for s in calls["symbols"]] == ["save"]  # the constant is left out
    assert calls["incoming"] == [{"caller": "get_items", "path": "app/api/routes.py", "callee": "save"}]
    assert calls["outgoing"] == [{"caller": "save", "path": "app/misc/loop.py", "callee": "tick"}]


@pytest.mark.asyncio
async def test_an_unknown_file_is_an_empty_answer(db_session, kb) -> None:
    calls = await AtlasService(db_session, kb).calls("nowhere.py")
    assert calls == {"path": "nowhere.py", "symbols": [], "outgoing": [], "incoming": []}
