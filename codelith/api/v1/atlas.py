"""
The atlas, over HTTP: the codebase as a map, and one file from the inside.

On the base router for the same reason as the pre-flight. Nothing here derives
anything of its own; it lays out what analysis already stored so a person can read it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.dependencies import CurrentUser, DbSession
from codelith.knowledge.atlas import AtlasService
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.shape import component_tiers
from codelith.models.knowledge import KnowledgeBase
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Atlas"])


class AtlasComponentOut(BaseModel):
    name: str
    description: str
    group: str


class AtlasNodeOut(BaseModel):
    id: str
    path: str
    kind: str
    component: int
    loc: int = 0
    language: str | None = None
    symbols: int = 0
    fact: str | None = None
    detail: str | None = None
    source: str | None = None
    #: Why a file is in its part.
    why: str | None = None


class AtlasOut(BaseModel):
    commit: str | None
    components: list[AtlasComponentOut]
    nodes: list[AtlasNodeOut]
    #: `[importer, imported]` as indexes into `nodes`; for a fact node, `[file, fact]`.
    edges: list[tuple[int, int]]
    kinds: dict[str, int]
    #: Each component's column, left to right in the order a request meets them
    #: (`knowledge/shape.py`); -1 for an empty one. The same columns a review checks
    #: a change against, so the map and the review cannot disagree.
    tiers: list[int] = Field(default_factory=list)


class SymbolOut(BaseModel):
    name: str | None
    qname: str
    kind: str | None
    line: int | None
    end_line: int | None


class CallOut(BaseModel):
    caller: str
    #: The *other* file: where the callee lives for an outgoing call, where the
    #: caller lives for an incoming one.
    path: str
    callee: str


class FileCallsOut(BaseModel):
    path: str
    symbols: list[SymbolOut] = Field(default_factory=list)
    outgoing: list[CallOut] = Field(default_factory=list)
    incoming: list[CallOut] = Field(default_factory=list)


async def servable_kb(db: AsyncSession, project_id: int) -> KnowledgeBase:
    """The newest knowledge base, or a 409 saying the codebase has not been analysed."""
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
    return kb


@router.get("/{project_id}/graph", response_model=AtlasOut)
async def atlas(project_id: int, db: DbSession, user: CurrentUser) -> AtlasOut:
    """
    Every file, its kind and component, and what imports what, in one call.

    Facts that are not source files (configuration files, datastores, outside
    services) are nodes of their own, linked from the file that declares them.
    """
    await ProjectService(db).get(project_id, user)
    built = await AtlasService(db, await servable_kb(db, project_id)).build()
    return AtlasOut(
        commit=built.commit,
        components=[
            AtlasComponentOut(name=c.name, description=c.description, group=c.group)
            for c in built.components
        ],
        nodes=[
            AtlasNodeOut(
                id=n.id,
                path=n.path,
                kind=n.kind,
                component=n.component,
                loc=n.loc,
                language=n.language,
                symbols=n.symbols,
                fact=n.fact,
                detail=n.detail,
                source=n.source,
                why=n.why,
            )
            for n in built.nodes
        ],
        edges=built.edges,
        kinds=built.kinds,
        tiers=component_tiers(built),
    )


@router.get("/{project_id}/graph/calls", response_model=FileCallsOut)
async def file_calls(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    path: str = Query(min_length=1, max_length=500, description="A repository path."),
) -> FileCallsOut:
    """
    One file's functions and classes, the calls it makes into other files, and the
    calls other files make into it. An unknown path is an empty answer, not a 404.
    """
    await ProjectService(db).get(project_id, user)
    return FileCallsOut(**await AtlasService(db, await servable_kb(db, project_id)).calls(path))
