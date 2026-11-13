"""
Running and keeping reviews of changes.

`knowledge/review.py` decides what a change means; this finds the reading to check it
against, collects the change when the server can (a folder on this machine), and keeps
the report so the studio can show it — whoever asked for it: the studio, `codelith
review` in a terminal, or an agent through MCP's `review_changes`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.knowledge import changes as change_io
from codelith.knowledge.changes import ChangeError, ChangeSet
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.review import Review, ReviewService
from codelith.models.knowledge import KnowledgeBase
from codelith.models.project import ProjectSource
from codelith.models.review import ChangeReview


async def latest_reading(db: AsyncSession, project_id: int) -> KnowledgeBase:
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
            detail="This codebase has not been analysed yet, so there is nothing to review a change against.",
        )
    return kb


async def local_folder(db: AsyncSession, project_id: int) -> Path | None:
    """The folder the codebase is read from, when it is one on this machine."""
    source = (
        await db.execute(
            select(ProjectSource).where(ProjectSource.project_id == project_id).order_by(ProjectSource.id).limit(1)
        )
    ).scalar_one_or_none()
    if source is None or source.source_type != "local":
        return None
    return Path(source.url_or_path).expanduser()


async def collect_working_copy(folder: Path, kb: KnowledgeBase, against: str | None, head: str | None) -> ChangeSet:
    """
    The change in a working copy. Against the reading's own commit by default — "what
    has changed that the knowledge has not seen" — and against `HEAD` when that commit
    is not in this repository's history.
    """
    def run() -> ChangeSet:
        base = against
        if not base:
            root = folder.resolve()
            base = kb.commit_sha if kb.commit_sha and change_io.has_commit(root, kb.commit_sha) else "HEAD"
        return change_io.collect(folder, base, head)

    try:
        return await asyncio.to_thread(run)
    except ChangeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def run_and_keep(
    db: AsyncSession,
    project_id: int,
    change: ChangeSet,
    *,
    source: str,
    user_id: int | None = None,
    client: str | None = None,
    kb: KnowledgeBase | None = None,
) -> tuple[ChangeReview, Review]:
    kb = kb or await latest_reading(db, project_id)
    review = await ReviewService(db, kb).review(change)
    row = ChangeReview(
        project_id=project_id,
        kb_id=kb.id,
        created_by=user_id,
        source=source,
        client=client,
        base=change.base[:120],
        head=(change.head or None) and change.head[:120],
        verdict=review.verdict,
        risk=review.risk,
        file_count=len(review.files),
        summary=review.summary,
        # The prose report too, so a terminal or an agent can print exactly what the
        # studio shows without a second renderer drifting from this one.
        report_json={**review.to_dict(), "brief": review.brief()},
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, review


async def list_reviews(db: AsyncSession, project_id: int, limit: int = 50) -> list[ChangeReview]:
    rows = await db.execute(
        select(ChangeReview)
        .where(ChangeReview.project_id == project_id)
        .order_by(ChangeReview.created_at.desc(), ChangeReview.id.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


async def get_review(db: AsyncSession, project_id: int, review_id: int) -> ChangeReview:
    row = await db.get(ChangeReview, review_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="No such review.")
    return row
