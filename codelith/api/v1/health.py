"""
Health over time: where danger collects (hotspots) and whether the codebase is getting
better or worse (the timeline). See `knowledge/hotspots.py` and `knowledge/timeline.py`.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query
from pydantic import BaseModel

from codelith.api.v1.atlas import servable_kb
from codelith.dependencies import CurrentUser, DbSession
from codelith.knowledge.churn import Churn
from codelith.knowledge.churn import read as read_churn
from codelith.knowledge.hotspots import HotspotService
from codelith.knowledge.timeline import TimelineService
from codelith.models.knowledge import KnowledgeBase
from codelith.services.project_service import ProjectService
from codelith.services.review_service import local_folder

router = APIRouter(prefix="/projects", tags=["Health"])


class HotspotOut(BaseModel):
    path: str
    kind: str
    component: str
    changes: int
    changes_total: int
    reach: int
    tests: int
    score: float
    level: str


class HotspotsOut(BaseModel):
    commit: str | None
    available: bool
    reason: str = ""
    window: str
    days: int
    commits: int
    recent_commits: int
    since: str | None
    shallow: bool
    hotspots: list[HotspotOut]


class PartPointOut(BaseModel):
    name: str
    files: int
    loc: int
    links_out: int


class ReadingOut(BaseModel):
    kb_id: int
    commit: str | None
    completed_at: str | None
    files: int
    loc: int
    links: int
    backwards: list[tuple[str, str]]
    tangled: list[tuple[str, str]]
    #: Backwards links this reading has and the one before it did not.
    new_backwards: list[tuple[str, str]]
    parts: list[PartPointOut]


class TimelineOut(BaseModel):
    readings: list[ReadingOut]


async def _churn(db, kb: KnowledgeBase) -> Churn | None:
    """
    The reading's change history: kept with it since history was read at analysis, and
    for an older reading of a folder on this machine, counted now — up to the reading's
    own commit, without fetching anything — and kept, so it is counted once.
    """
    kept = Churn.from_json(kb.churn_json)
    if kept is not None:
        return kept
    folder = await local_folder(db, kb.project_id)
    if folder is None or not folder.exists():
        return None
    paths = set((kb.file_hashes_json or {}).keys()) or None
    churn = await asyncio.to_thread(read_churn, folder, paths, deepen=False, rev=kb.commit_sha)
    if churn is None and kb.commit_sha:
        # The commit is not in this folder's history (rewritten, or another clone).
        return None
    if churn is not None:
        kb.churn_json = churn.to_json()
        await db.commit()
    return churn


@router.get("/{project_id}/hotspots", response_model=HotspotsOut)
async def hotspots(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=15, ge=1, le=100),
) -> HotspotsOut:
    """Files that change often, that much of the code depends on, and that no test reaches."""
    await ProjectService(db).get(project_id, user)
    kb = await servable_kb(db, project_id)
    report = await HotspotService(db, kb).rank(limit=limit, churn=await _churn(db, kb))
    return HotspotsOut(
        commit=kb.commit_sha,
        available=report.available,
        reason=report.reason,
        window=report.window,
        days=report.days,
        commits=report.commits,
        recent_commits=report.recent_commits,
        since=report.since,
        shallow=report.shallow,
        hotspots=[HotspotOut(**{f: getattr(h, f) for f in HotspotOut.model_fields}) for h in report.hotspots],
    )


@router.get("/{project_id}/timeline", response_model=TimelineOut)
async def timeline(project_id: int, db: DbSession, user: CurrentUser) -> TimelineOut:
    """Each kept reading's size, links between parts, and links against the columns."""
    await ProjectService(db).get(project_id, user)
    readings = await TimelineService(db, project_id).readings()
    out: list[ReadingOut] = []
    before: set[tuple[str, str]] | None = None
    for r in readings:
        now = set(r.backwards)
        out.append(
            ReadingOut(
                kb_id=r.kb_id,
                commit=r.commit,
                completed_at=r.completed_at,
                files=r.files,
                loc=r.loc,
                links=r.links,
                backwards=r.backwards,
                tangled=r.tangled,
                new_backwards=sorted(now - before) if before is not None else [],
                parts=[PartPointOut(name=p.name, files=p.files, loc=p.loc, links_out=p.links_out) for p in r.parts],
            )
        )
        before = now
    return TimelineOut(readings=out)
