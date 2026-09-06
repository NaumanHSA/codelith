"""
The pre-flight, over HTTP.

The same answer `before_edit` returns over MCP, in JSON rather than prose. Two
transports over one service, for the same reason the MCP server is not an app: an
agent wants a paragraph it can read, a studio wants fields it can lay out, and neither
justifies a second implementation of the lookup.

It is on the base router rather than under an app because the pre-flight is not one —
nothing here derives anything of its own, it assembles what analysis already stored.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from codelith.dependencies import CurrentUser, DbSession
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.preflight import PreflightService
from codelith.models.knowledge import KnowledgeBase
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Pre-flight"])


class CallerOut(BaseModel):
    file: str
    symbol: str


class ReachedOut(BaseModel):
    path: str
    distance: int
    is_test: bool


class CitedByOut(BaseModel):
    address: str
    title: str


class PreflightOut(BaseModel):
    target: str
    found: bool
    kind: str
    risk: str
    headline: str
    #: The prose an agent gets over MCP, returned here too so the studio can show
    #: exactly what a connected agent would see rather than a prettier paraphrase.
    brief: str
    files: list[str] = Field(default_factory=list)
    defined_at: list[str] = Field(default_factory=list)
    callers: list[CallerOut] = Field(default_factory=list)
    dependents: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    #: `reach_weight`: capped reach plus five per written page. The ranking every
    #: caller is supposed to sort on, and the studio could not read it.
    weight: int = 0
    reached: list[ReachedOut] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    documented_in: list[CitedByOut] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)


@router.get("/{project_id}/preflight", response_model=PreflightOut)
async def preflight(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    target: str = Query(min_length=1, max_length=300, description="A path or a symbol name."),
) -> PreflightOut:
    """
    What an edit to `target` would touch.

    A target that resolves to nothing is a 200 with `found: false`, not a 404. "I have
    never seen that file" is an answer about the codebase; a 404 says the endpoint
    does not exist, and a caller cannot tell the two apart.
    """
    await ProjectService(db).get(project_id, user)

    kb = (
        await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.project_id == project_id)
            .order_by(KnowledgeBase.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if kb is None or not KBStatus(kb.status).can_serve_features:
        raise HTTPException(
            status_code=409,
            detail="This codebase has not been analysed yet. Run an analysis first.",
        )

    report = await PreflightService(db, kb.id, project_id).inspect(target)
    return PreflightOut(
        target=report.target,
        found=report.found,
        kind=report.kind,
        risk=report.risk,
        headline=report.headline(),
        brief=report.brief(),
        files=report.files,
        defined_at=report.defined_at,
        callers=[CallerOut(file=c.file, symbol=c.symbol) for c in report.callers],
        dependents=report.dependents,
        imports=report.imports,
        weight=report.weight,
        reached=[
            ReachedOut(path=r.path, distance=r.distance, is_test=r.is_test) for r in report.reached
        ],
        tests=report.tests,
        documented_in=[CitedByOut(address=p.address, title=p.title) for p in report.documented_in],
        facts=report.facts,
    )
