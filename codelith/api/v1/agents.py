"""
Which agents are attached over MCP, and what they asked.

The MCP server (`codelith/mcp/`) records each tool call it answers; this reads them
back for the studio. Admin-only, like the model settings beside it: what the agents on
this machine have been asking is an operator's view, and the arguments can name any
file in any codebase.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from codelith.dependencies import AdminUser, DbSession
from codelith.models.agent_call import AgentCall
from codelith.models.project import Project

router = APIRouter(prefix="/agents", tags=["Agents"])


class AgentOut(BaseModel):
    client: str
    calls: int
    first_seen: datetime
    last_seen: datetime


class AgentCallOut(BaseModel):
    id: int
    client: str
    tool: str
    project_id: int | None
    project_name: str | None
    args: dict = Field(default_factory=dict)
    summary: str | None
    ok: bool
    created_at: datetime


class AgentActivityOut(BaseModel):
    agents: list[AgentOut]
    calls: list[AgentCallOut]


@router.get("/activity", response_model=AgentActivityOut)
async def activity(
    db: DbSession,
    _: AdminUser,
    limit: int = Query(default=30, ge=1, le=200),
) -> AgentActivityOut:
    """Every client that has called a tool, and the most recent calls."""
    agents = (
        await db.execute(
            select(
                AgentCall.client,
                func.count(),
                func.min(AgentCall.created_at),
                func.max(AgentCall.created_at),
            )
            .group_by(AgentCall.client)
            .order_by(func.max(AgentCall.created_at).desc())
        )
    ).all()
    rows = (
        await db.execute(
            select(AgentCall, Project.name)
            .outerjoin(Project, Project.id == AgentCall.project_id)
            .order_by(AgentCall.created_at.desc(), AgentCall.id.desc())
            .limit(limit)
        )
    ).all()
    return AgentActivityOut(
        agents=[
            AgentOut(client=c, calls=n, first_seen=first, last_seen=last)
            for c, n, first, last in agents
        ],
        calls=[
            AgentCallOut(
                id=call.id,
                client=call.client,
                tool=call.tool,
                project_id=call.project_id,
                project_name=name,
                args=call.args_json or {},
                summary=call.summary,
                ok=call.ok,
                created_at=call.created_at,
            )
            for call, name in rows
        ],
    )


#: How an answer says it found nothing. Every tool phrases emptiness as a sentence (see
#: `knowledge/tools.py`), which is what makes this readable from the record alone.
_EMPTY = (
    "nothing ",
    "no route",
    "no codebase",
    "found no",
    "is not in this knowledge base",
    "this codebase has no",
    "could not read",
)
#: Arguments that say what was asked, in the order they are worth showing.
_ASKED = ("target", "query", "entry", "path", "symbol", "kind", "name")


class AgentGapOut(BaseModel):
    tool: str
    asked: str
    project_id: int | None
    project_name: str | None
    times: int
    empty: bool
    clients: list[str]
    last_seen: datetime


@router.get("/gaps", response_model=list[AgentGapOut])
async def gaps(
    db: DbSession,
    _: AdminUser,
    window: int = Query(default=500, ge=50, le=5000),
) -> list[AgentGapOut]:
    """
    What agents asked and could not get: questions answered with "nothing", and the same
    question asked three times or more (an agent repeating itself has not found what it
    wanted). Read from the recorded calls — the to-do list for what analysis is missing.
    """
    rows = (
        await db.execute(
            select(AgentCall, Project.name)
            .outerjoin(Project, Project.id == AgentCall.project_id)
            .where(AgentCall.tool != "list_codebases")
            .order_by(AgentCall.created_at.desc(), AgentCall.id.desc())
            .limit(window)
        )
    ).all()
    groups: dict[tuple, dict] = {}
    for call, name in rows:
        args = call.args_json or {}
        asked = next((str(args[k]) for k in _ASKED if args.get(k)), "")
        key = (call.project_id, call.tool, asked.strip().lower())
        first = (call.summary or "").strip().lower()
        g = groups.setdefault(
            key,
            {
                "tool": call.tool,
                "asked": asked,
                "project_id": call.project_id,
                "project_name": name,
                "times": 0,
                "empty": False,
                "clients": set(),
                "last_seen": call.created_at,
            },
        )
        g["times"] += 1
        g["clients"].add(call.client)
        g["empty"] = g["empty"] or not call.ok or first.startswith(_EMPTY) or any(p in first for p in _EMPTY[3:])
        if call.created_at > g["last_seen"]:
            g["last_seen"] = call.created_at
    found = [g for g in groups.values() if g["empty"] or g["times"] >= 3]
    found.sort(key=lambda g: (not g["empty"], -g["times"], -g["last_seen"].timestamp()))
    return [AgentGapOut(**{**g, "clients": sorted(g["clients"])}) for g in found[:40]]
