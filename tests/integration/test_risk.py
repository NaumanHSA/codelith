"""
Every file ranked by what an edit to it would touch.

The ranking is the pre-flight's arithmetic run over the whole map, so these pin that it
agrees with the pre-flight: the same reach, the same weight, the same level, and tests
counted as protection rather than ranked as risks themselves.
"""

from __future__ import annotations

import uuid

import pytest

from codelith.knowledge.constants import KBStatus
from codelith.knowledge.preflight import PreflightService, risk_level
from codelith.knowledge.risk import RiskService
from codelith.models.graph import GraphFile, GraphImport
from codelith.models.knowledge import KBModule, KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project


@pytest.fixture
async def kb(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-rk-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="rk", slug=f"rk-{tag}")
    db_session.add(project)
    await db_session.flush()
    base = KnowledgeBase(project_id=project.id, commit_sha=tag, status=KBStatus.READY)
    db_session.add(base)
    await db_session.flush()

    key = {"project_id": project.id, "kb_id": base.id}
    db_session.add(KBModule(kb_id=base.id, path="app", name="app", kind="package", role="service"))
    db_session.add(KBModule(kb_id=base.id, path="tests", name="tests", kind="package", role="test", is_test=True))
    # core <- a <- b <- c, and a test that imports a. core reaches a, b, c, the test.
    files = ["app/core.py", "app/a.py", "app/b.py", "app/c.py", "app/leaf.py", "tests/test_a.py"]
    for path in files:
        db_session.add(GraphFile(**key, path=path, module_key=path.split("/")[0], language="python", loc=5))
    for src, dst in [
        ("app/a.py", "app/core.py"),
        ("app/b.py", "app/a.py"),
        ("app/c.py", "app/b.py"),
        ("tests/test_a.py", "app/a.py"),
    ]:
        db_session.add(GraphImport(**key, src=src, dst=dst))
    await db_session.flush()
    return base


@pytest.mark.asyncio
async def test_the_most_depended_on_file_ranks_first(db_session, kb) -> None:
    ranked, total = await RiskService(db_session, kb).rank()
    assert total == 5  # the test file is not ranked
    top = ranked[0]
    assert top.path == "app/core.py"
    assert (top.direct, top.reach, top.tests) == (1, 4, 1)  # a, b, c, and the test
    assert ranked[-1].reach == 0


@pytest.mark.asyncio
async def test_it_agrees_with_the_preflight(db_session, kb) -> None:
    ranked, _ = await RiskService(db_session, kb).rank()
    by_path = {r.path: r for r in ranked}
    for path in ("app/core.py", "app/a.py", "app/leaf.py"):
        report = await PreflightService(db_session, kb.id, kb.project_id).inspect(path)
        row = by_path[path]
        assert row.reach == len(report.reached)
        assert row.weight == report.weight
        assert row.level == report.risk


def test_untested_is_an_amplifier_not_a_level() -> None:
    assert risk_level(0, False) == "low"
    assert risk_level(8, False) == "high"
    assert risk_level(8, True) == "moderate"
    assert risk_level(3, True) == "low"
    assert risk_level(3, False) == "moderate"
    assert risk_level(25, True) == "high"
