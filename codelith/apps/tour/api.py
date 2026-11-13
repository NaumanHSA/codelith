"""HTTP for the tour app."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from codelith.api.v1.atlas import servable_kb
from codelith.apps.tour.service import TourService
from codelith.dependencies import CurrentUser, DbSession
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/projects/{project_id}/tour", tags=["Tour"])


class TourFileOut(BaseModel):
    path: str
    note: str = ""


class StopOut(BaseModel):
    id: str
    title: str
    body: str
    parts: list[str]
    files: list[TourFileOut]
    flow: str | None = None


class TourOut(BaseModel):
    project: str
    commit: str | None
    stops: list[StopOut]


class TourMarkdownOut(BaseModel):
    filename: str
    markdown: str


@router.get("", response_model=TourOut)
async def get_tour(project_id: int, db: DbSession, user: CurrentUser) -> TourOut:
    """The stops of a walk through the codebase, built from the latest reading."""
    await ProjectService(db).get(project_id, user)
    tour = await TourService(db, await servable_kb(db, project_id)).build()
    return TourOut(
        project=tour.project,
        commit=tour.commit,
        stops=[
            StopOut(
                id=s.id,
                title=s.title,
                body=s.body,
                parts=s.parts,
                files=[TourFileOut(path=f.path, note=f.note) for f in s.files],
                flow=s.flow,
            )
            for s in tour.stops
        ],
    )


@router.get("/markdown", response_model=TourMarkdownOut)
async def get_tour_markdown(project_id: int, db: DbSession, user: CurrentUser) -> TourMarkdownOut:
    """The same tour as a document, for a README or an onboarding page."""
    await ProjectService(db).get(project_id, user)
    tour = await TourService(db, await servable_kb(db, project_id)).build()
    return TourMarkdownOut(filename="TOUR.md", markdown=tour.markdown())
