"""
What a codebase contains and where it is fragile, for the codebase page.

Two reads of what analysis stored: the facts it extracted (routes, env vars,
datastores, outside services…), which had no endpoint of their own and reached the
studio only as samples inside the knowledge-base summary; and every file ranked by
what an edit to it would touch (`knowledge/risk.py`).
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from codelith.api.v1.atlas import servable_kb
from codelith.dependencies import CurrentUser, DbSession
from codelith.knowledge.risk import DEPTH, RiskService
from codelith.models.knowledge import KBEntity
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Codebase"])

#: Facts returned for one kind. A codebase with more env vars than this has made its
#: point, and the page lists them rather than paging through them.
_FACT_CAP = 500


class FactOut(BaseModel):
    kind: str
    name: str
    source_path: str | None
    source_line: int | None
    data: dict = Field(default_factory=dict)


class FactsOut(BaseModel):
    #: Every kind found, with how many.
    kinds: dict[str, int]
    #: The facts of the requested kinds; empty when none was asked for.
    items: list[FactOut] = Field(default_factory=list)
    truncated: bool = False


class FileRiskOut(BaseModel):
    path: str
    kind: str
    component: str
    direct: int
    reach: int
    tests: int
    pages: int
    weight: int
    level: str


class RiskOut(BaseModel):
    depth: int
    ranked: int
    files: list[FileRiskOut]


@router.get("/{project_id}/entities", response_model=FactsOut)
async def facts(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    kind: list[str] | None = Query(default=None, description="Fact kinds to list."),
) -> FactsOut:
    """The facts analysis extracted: counts for every kind, and the facts of `kind`."""
    await ProjectService(db).get(project_id, user)
    kb = await servable_kb(db, project_id)

    counts = dict(
        (
            await db.execute(
                select(KBEntity.kind, func.count()).where(KBEntity.kb_id == kb.id).group_by(KBEntity.kind)
            )
        ).all()
    )
    items: list[FactOut] = []
    truncated = False
    if kind:
        rows = (
            await db.execute(
                select(KBEntity.kind, KBEntity.name, KBEntity.source_path, KBEntity.source_line, KBEntity.data_json)
                .where(KBEntity.kb_id == kb.id, KBEntity.kind.in_(kind))
                .order_by(KBEntity.kind, KBEntity.source_path, KBEntity.source_line, KBEntity.name)
                .limit(_FACT_CAP + 1)
            )
        ).all()
        truncated = len(rows) > _FACT_CAP
        items = [
            FactOut(
                kind=k,
                name=n,
                source_path=p,
                source_line=ln,
                data=d if isinstance(d, dict) else {},
            )
            for k, n, p, ln, d in rows[:_FACT_CAP]
        ]
    return FactsOut(kinds=counts, items=items, truncated=truncated)


@router.get("/{project_id}/risk", response_model=RiskOut)
async def risk(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=15, ge=1, le=200),
) -> RiskOut:
    """
    Files ranked by `reach_weight`: what reaches them within three hops, plus five per
    written page that cites them. Each says whether a test is among what reaches it.
    """
    await ProjectService(db).get(project_id, user)
    kb = await servable_kb(db, project_id)
    ranked, total = await RiskService(db, kb).rank(limit)
    return RiskOut(
        depth=DEPTH,
        ranked=total,
        files=[FileRiskOut(**asdict(r)) for r in ranked],
    )
