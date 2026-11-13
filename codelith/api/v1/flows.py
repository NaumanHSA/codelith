"""
Flows over HTTP: every way into a codebase, and the path each takes through it.

Base, like the graph beside it: a flow is laid out from what the reading stored (the
call graph, the facts, the map) and derives nothing of its own. See `knowledge/flows.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from codelith.api.v1.atlas import servable_kb
from codelith.dependencies import CurrentUser, DbSession
from codelith.knowledge.diagrams import request_flow
from codelith.knowledge.flows import FlowService
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Flows"])


class FlowSummaryOut(BaseModel):
    id: str
    kind: str
    label: str
    name: str
    path: str
    line: int | None
    steps: int
    chain: int
    ends: str | None
    parts: list[str]


class FlowsOut(BaseModel):
    commit: str | None
    flows: list[FlowSummaryOut]


class FlowStepOut(BaseModel):
    qname: str
    path: str
    line: int | None
    depth: int
    parent: int | None
    kind: str | None
    part: str | None
    ends: str | None


class FlowOut(FlowSummaryOut):
    all_steps: list[FlowStepOut]
    chain_steps: list[int]
    #: The chain as prose, the same text an agent gets from `trace_flow`.
    brief: str
    #: The chain as D2 source, for a written page. None when it is too short to draw.
    diagram: str | None


@router.get("/{project_id}/flows", response_model=FlowsOut)
async def list_flows(project_id: int, db: DbSession, user: CurrentUser) -> FlowsOut:
    await ProjectService(db).get(project_id, user)
    kb = await servable_kb(db, project_id)
    flows = await FlowService(db, kb).flows()
    return FlowsOut(commit=kb.commit_sha, flows=[FlowSummaryOut(**f.summary()) for f in flows])


@router.get("/{project_id}/flows/{flow_id}", response_model=FlowOut)
async def get_flow(project_id: int, flow_id: str, db: DbSession, user: CurrentUser) -> FlowOut:
    await ProjectService(db).get(project_id, user)
    kb = await servable_kb(db, project_id)
    flow = await FlowService(db, kb).find(flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="No such way into this codebase.")
    chain = [{"qname": flow.steps[i].qname, "path": flow.steps[i].path, "part": flow.steps[i].part} for i in flow.chain]
    return FlowOut(**flow.to_dict(), brief=flow.brief(), diagram=request_flow(flow.name, chain, flow.ends))
