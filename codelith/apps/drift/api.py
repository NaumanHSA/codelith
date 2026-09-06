"""HTTP for the drift app."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from codelith.apps.drift.service import DriftService
from codelith.dependencies import CurrentUser, DbSession
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/projects/{project_id}/drift", tags=["Drift"])


class GenerationOut(BaseModel):
    id: int
    commit_sha: str | None
    status: str
    created_at: str


class ModuleChangeOut(BaseModel):
    path: str
    name: str
    change: str
    loc_before: int
    loc_after: int
    loc_delta: int


class EntityChangeOut(BaseModel):
    kind: str
    name: str
    change: str
    source_path: str | None


class PageAtRiskOut(BaseModel):
    address: str
    title: str
    changed_files: list[str]
    reason: str


class ServiceChangeOut(BaseModel):
    name: str
    change: str
    type_before: str = ""
    type_after: str = ""


class RelationChangeOut(BaseModel):
    source: str
    target: str
    change: str
    kind: str = ""
    kind_before: str = ""


class DriftOut(BaseModel):
    project_id: int
    from_commit: str | None
    to_commit: str | None
    summary: str
    comparable: bool
    modules: list[ModuleChangeOut] = []
    entities: list[EntityChangeOut] = []
    pages_at_risk: list[PageAtRiskOut] = []
    services: list[ServiceChangeOut] = []
    relations: list[RelationChangeOut] = []
    #: Separate from `comparable`, which is about having two readings at all. This
    #: is about both of them having an architecture map: a reading taken before that
    #: column existed can be diffed for modules and not for shape, and the page
    #: should say so rather than show an empty diff that looks like "no change".
    architecture_comparable: bool = False


@router.get("", response_model=DriftOut)
async def get_drift(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    before: int | None = None,
    after: int | None = None,
):
    """
    What changed between two readings of this project.

    Defaults to the two most recent. A project analysed once is not an error and not
    an empty diff — it is `comparable: false`, because there is no history to compare
    against yet, and saying "nothing changed" would be a different and untrue claim.

    `architecture_comparable` is the same distinction one level down. Both readings
    have modules; only readings taken since the architecture agent landed have a map.
    Diffing a map against nothing would report every service as newly added, so it
    reports nothing and says which case you are in.
    """
    await ProjectService(db).get(project_id, user)  # authorises and 404s
    svc = DriftService(db)

    if before is None or after is None:
        pair = await svc.latest_pair(project_id)
        if pair is None:
            return DriftOut(
                project_id=project_id,
                from_commit=None,
                to_commit=None,
                comparable=False,
                summary=(
                    "This codebase has been read once. Analyse it again after the code "
                    "moves on and drift will have two points to compare."
                ),
            )
        before, after = pair[0].id, pair[1].id

    report = await svc.compare(project_id, before, after)
    return DriftOut(
        project_id=report.project_id,
        from_commit=report.from_commit,
        to_commit=report.to_commit,
        comparable=True,
        summary=report.summary(),
        modules=[
            ModuleChangeOut(
                path=m.path, name=m.name, change=m.change,
                loc_before=m.loc_before, loc_after=m.loc_after, loc_delta=m.loc_delta,
            )
            for m in report.modules
        ],
        entities=[
            EntityChangeOut(kind=e.kind, name=e.name, change=e.change, source_path=e.source_path)
            for e in report.entities
        ],
        pages_at_risk=[
            PageAtRiskOut(
                address=p.address, title=p.title,
                changed_files=p.changed_files, reason=p.reason,
            )
            for p in report.pages_at_risk
        ],
        architecture_comparable=report.architecture_comparable,
        services=[
            ServiceChangeOut(
                name=x.name, change=x.change,
                type_before=x.type_before, type_after=x.type_after,
            )
            for x in report.services
        ],
        relations=[
            RelationChangeOut(
                source=r.source, target=r.target, change=r.change,
                kind=r.kind, kind_before=r.kind_before,
            )
            for r in report.relations
        ],
    )


@router.get("/generations", response_model=list[GenerationOut])
async def list_generations(project_id: int, db: DbSession, user: CurrentUser):
    """Every reading of this project, newest first — the points drift can compare."""
    await ProjectService(db).get(project_id, user)
    gens = await DriftService(db).generations(project_id)
    if not gens:
        raise HTTPException(status_code=404, detail="This project has never been analysed.")
    return [
        GenerationOut(
            id=g.id, commit_sha=g.commit_sha, status=g.status,
            created_at=g.created_at.isoformat(),
        )
        for g in gens
    ]
