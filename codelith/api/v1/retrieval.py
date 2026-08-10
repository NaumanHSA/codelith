"""
Retrieval inspection — a development-only window onto what a question retrieves.

Not the Ask-the-code feature. It returns *evidence*, never an answer, and calls no
model. Its purpose is to make the substrate built in K1–K3 legible enough to judge
before an agent is written on top of it.

Disabled outside development. It exposes a raw retrieval surface with no rate limit
and no cost ceiling, and the studio has no use for it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from codelith.config import get_settings
from codelith.dependencies import CurrentUser, DbSession
from codelith.knowledge.questions import QuestionRouter
from codelith.models.knowledge import KnowledgeBase
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/retrieval", tags=["Retrieval (dev)"])


class EvidenceOut(BaseModel):
    kind: str
    title: str
    body: str
    why: str
    score: float | None = None


class RetrievalOut(BaseModel):
    kb_id: int
    question: str
    intents: list[str]
    symbols: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    entity_kinds: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    items: list[EvidenceOut] = Field(default_factory=list)


class RetrievalIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    token_budget: int = Field(default=6000, ge=500, le=32000)


@router.post("/projects/{project_id}/inspect", response_model=RetrievalOut)
async def inspect_retrieval(
    project_id: int, req: RetrievalIn, db: DbSession, user: CurrentUser
) -> RetrievalOut:
    """
    What a question retrieves, and why each piece was retrieved.

    Deliberately returns no prose answer: an answer would hide exactly the thing this
    endpoint exists to show.
    """
    if get_settings().is_production:
        raise HTTPException(status_code=404, detail="Not found")

    await ProjectService(db).get(project_id, user)

    kb = (
        await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.project_id == project_id)
            .order_by(KnowledgeBase.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if kb is None:
        raise HTTPException(
            status_code=404,
            detail="This project has no knowledge base. Analyse it first.",
        )

    bundle = await QuestionRouter(db, kb.id, project_id).gather(
        req.question, token_budget=req.token_budget
    )
    return RetrievalOut(
        kb_id=kb.id,
        question=req.question,
        intents=bundle.plan.intents,
        symbols=bundle.plan.symbols,
        paths=bundle.plan.paths,
        entity_kinds=bundle.plan.entity_kinds,
        counts=bundle.counts,
        items=[
            EvidenceOut(kind=i.kind, title=i.title, body=i.body, why=i.why, score=i.score)
            for i in bundle.items
        ],
    )
