"""
Reviews of changes, over HTTP.

`POST` reviews a change: one the caller collected (the CLI sends what `git` says in the
checkout it runs in) or, for a codebase read from a folder on this machine, the
working copy itself. Either way the report is kept, and the `GET`s are how the studio
reads reviews made from anywhere — the studio, a terminal, an agent.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from codelith.dependencies import CurrentUser, DbSession
from codelith.knowledge.changes import ChangeSet
from codelith.services import review_service
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Review"])


class ChangedFileIn(BaseModel):
    path: str = Field(max_length=1000)
    status: str = "modified"
    old_path: str | None = Field(default=None, max_length=1000)
    old_ranges: list[tuple[int, int]] = Field(default_factory=list)
    new_ranges: list[tuple[int, int]] = Field(default_factory=list)
    content: str | None = None


class ChangeSetIn(BaseModel):
    base: str = Field(max_length=200)
    head: str | None = Field(default=None, max_length=200)
    files: list[ChangedFileIn] = Field(default_factory=list)
    skipped: int = 0


class ReviewRequest(BaseModel):
    #: A change the caller collected. Omit to review the working copy of a codebase
    #: read from a folder on this machine.
    change: ChangeSetIn | None = None
    #: For the working copy: what to compare against. Defaults to the reading's commit.
    against: str | None = Field(default=None, max_length=200)
    head: str | None = Field(default=None, max_length=200)
    source: str = Field(default="studio", pattern="^(studio|cli|mcp)$")


class ReviewSummaryOut(BaseModel):
    id: int
    created_at: datetime
    source: str
    client: str | None
    base: str
    head: str | None
    verdict: str
    risk: str
    file_count: int
    summary: str


class ReviewOut(ReviewSummaryOut):
    kb_id: int | None
    report: dict


class ReviewsOut(BaseModel):
    reviews: list[ReviewSummaryOut]
    #: Whether this server can read the working copy itself (a local folder).
    can_review_working_copy: bool
    #: The commit the knowledge describes, which a review compares against by default.
    commit: str | None


def _out(row) -> ReviewOut:
    return ReviewOut(
        id=row.id,
        created_at=row.created_at,
        source=row.source,
        client=row.client,
        base=row.base,
        head=row.head,
        verdict=row.verdict,
        risk=row.risk,
        file_count=row.file_count,
        summary=row.summary,
        kb_id=row.kb_id,
        report=row.report_json or {},
    )


@router.post("/{project_id}/reviews", response_model=ReviewOut, status_code=201)
async def create_review(project_id: int, req: ReviewRequest, db: DbSession, user: CurrentUser) -> ReviewOut:
    await ProjectService(db).get(project_id, user)
    kb = await review_service.latest_reading(db, project_id)
    if req.change is not None:
        change = ChangeSet.from_dict(req.change.model_dump())
    else:
        folder = await review_service.local_folder(db, project_id)
        if folder is None:
            raise HTTPException(
                status_code=422,
                detail="This codebase is not read from a folder on this machine, so the server has no working "
                "copy to look at. Run `codelith review` in your checkout, or let your agent call review_changes.",
            )
        change = await review_service.collect_working_copy(folder, kb, req.against, req.head)
    row, _ = await review_service.run_and_keep(db, project_id, change, source=req.source, user_id=user.id, kb=kb)
    return _out(row)


@router.get("/{project_id}/reviews", response_model=ReviewsOut)
async def list_reviews(project_id: int, db: DbSession, user: CurrentUser) -> ReviewsOut:
    await ProjectService(db).get(project_id, user)
    rows = await review_service.list_reviews(db, project_id)
    folder = await review_service.local_folder(db, project_id)
    try:
        kb = await review_service.latest_reading(db, project_id)
        commit = kb.commit_sha
    except HTTPException:
        commit = None
    return ReviewsOut(
        reviews=[ReviewSummaryOut(**_out(r).model_dump(exclude={"kb_id", "report"})) for r in rows],
        can_review_working_copy=folder is not None,
        commit=commit,
    )


@router.get("/{project_id}/reviews/{review_id}", response_model=ReviewOut)
async def get_review(project_id: int, review_id: int, db: DbSession, user: CurrentUser) -> ReviewOut:
    await ProjectService(db).get(project_id, user)
    return _out(await review_service.get_review(db, project_id, review_id))
