"""
Agents attached over MCP leave a record the studio can show.

The server answers first and records second, and a record that cannot be written must
never cost the agent its answer.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from codelith.knowledge.constants import KBStatus
from codelith.mcp import server as mcp_server
from codelith.models.agent_call import AgentCall
from codelith.models.knowledge import KnowledgeBase
from codelith.models.organization import Organization
from codelith.models.project import Project


@pytest.fixture
async def kb(db_session):
    tag = uuid.uuid4().hex[:8]
    org = Organization(name="o", slug=f"o-ag-{tag}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="ag", slug=f"ag-{tag}")
    db_session.add(project)
    await db_session.flush()
    base = KnowledgeBase(project_id=project.id, commit_sha=tag, status=KBStatus.READY)
    db_session.add(base)
    await db_session.commit()
    return base


@pytest.fixture
def same_session(monkeypatch, db_session):
    """Point the server's session factory at the test database."""

    class _Ctx:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(mcp_server, "AsyncSessionLocal", lambda: _Ctx())


@pytest.mark.asyncio
async def test_a_call_is_recorded_with_its_codebase(db_session, kb, same_session) -> None:
    await mcp_server.record_call(
        "claude-code", "before_edit", {"codebase_id": kb.id, "target": "client.py"},
        "\napp/client.py — high risk to edit.\nmore", True,
    )
    row = (await db_session.execute(select(AgentCall).where(AgentCall.kb_id == kb.id))).scalar_one()
    assert row.client == "claude-code"
    assert row.project_id == kb.project_id
    assert row.args_json == {"target": "client.py"}  # the codebase id is its own column
    assert row.summary == "app/client.py — high risk to edit."
    assert row.ok is True


@pytest.mark.asyncio
async def test_a_record_that_cannot_be_written_does_not_raise(monkeypatch) -> None:
    def broken():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(mcp_server, "AsyncSessionLocal", broken)
    await mcp_server.record_call("cursor", "list_codebases", {}, "2 codebases", True)


@pytest.mark.asyncio
async def test_a_codebase_that_no_longer_exists_is_still_recorded(db_session, same_session) -> None:
    await mcp_server.record_call("cursor", "search_code", {"codebase_id": 987654, "query": "x"}, "", True)
    row = (await db_session.execute(select(AgentCall).where(AgentCall.kb_id == 987654))).scalar_one()
    assert row.project_id is None
    assert row.summary is None


@pytest.mark.asyncio
async def test_what_agents_could_not_find_is_listed(db_session, kb, same_session) -> None:
    """Empty answers and questions asked again and again; a call that found something,
    asked once, is not a gap."""
    from codelith.api.v1.agents import gaps

    record = mcp_server.record_call
    await record("claude-code", "before_edit", {"codebase_id": kb.id, "target": "nowhere.py"}, "Nothing is known about nowhere.py.", True)
    for _ in range(3):
        await record("cursor", "search_code", {"codebase_id": kb.id, "query": "retry policy"}, "app/retry.py — 3 matches", True)
    await record("claude-code", "before_edit", {"codebase_id": kb.id, "target": "app/client.py"}, "app/client.py — high risk to edit.", True)

    found = await gaps(db_session, None, window=500)  # type: ignore[arg-type]
    mine = [g for g in found if g.project_id == kb.project_id]
    asked = {(g.tool, g.asked): g for g in mine}

    assert asked[("before_edit", "nowhere.py")].empty
    repeated = asked[("search_code", "retry policy")]
    assert not repeated.empty and repeated.times == 3 and repeated.clients == ["cursor"]
    assert ("before_edit", "app/client.py") not in asked
    # Empty answers come first: they are the clearest sign something is missing.
    assert mine[0].empty
