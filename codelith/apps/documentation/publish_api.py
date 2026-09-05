"""
Publishing, from the studio's side.

Six routes, and the shape of the first one is the feature. `POST .../publish` does
not always publish: if the site serving right now is what this request would build,
it says so and starts nothing. Everything else here is what a person needs after
having shared a link — see it, replace it, roll it back, change the address, take it
away.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from codelith.apps.documentation.publishing.renderers import available_renderers
from codelith.apps.documentation.services.publication_service import PublicationService
from codelith.dependencies import CurrentUser, DbSession, ManagerUser
from codelith.schemas.publication import (
    PublicationOut,
    PublishAccepted,
    PublishRequest,
    RendererOut,
)
from codelith.services.audit_service import AuditService
from codelith.workers.dispatch import dispatch

router = APIRouter(tags=["Publishing"])


@router.get("/publishing/renderers", response_model=list[RendererOut])
async def list_renderers(user: CurrentUser) -> list[dict]:
    """
    What this machine can build.

    Asked before anything is offered, so the studio never presents a renderer that
    would fail at the build step. Same rule as document types, which are offered from
    the evidence that supports them.
    """
    return available_renderers()


@router.post(
    "/projects/{project_id}/site/publish",
    response_model=PublishAccepted,
    status_code=202,
)
async def publish_site(
    project_id: int,
    req: PublishRequest,
    db: DbSession,
    user: ManagerUser,
    request: Request,
) -> PublishAccepted:
    """
    Publish the live site, or a frozen version, at a URL.

    Answers `202` either way, because either way the caller's next move is to look at
    the publication it was handed. `unchanged` distinguishes the two: no job was
    started, nothing was written, and the site already serving is what this would
    have produced.
    """
    service = PublicationService(db)
    prepared = await service.prepare(
        project_id, user, target=req.target, renderer=req.renderer or "builtin", force=req.force
    )
    publication = prepared["publication"]

    if prepared["unchanged"]:
        await db.commit()
        return PublishAccepted(unchanged=True, publication=await _out(service, publication))

    from codelith.apps.documentation.tasks.publish_tasks import publish_site_task
    from codelith.schemas.job import JobCreate
    from codelith.services.job_service import JobService

    build = prepared["build"]
    job = await JobService(db).create(
        project_id=project_id,
        req=JobCreate(),
        user=user,
        job_type="publish",
        config_overrides={"publication_id": publication.id, "build_id": build.id},
        scope={"kind": "publish", "labels": [publication.target]},
    )
    build.job_id = job.id
    await _audit(db, user, request, "site.publish", publication.id)
    await db.commit()

    dispatch(publish_site_task, job.id, publication.id, build.id)
    return PublishAccepted(
        unchanged=False, publication=await _out(service, publication), job_id=job.id
    )


@router.get("/projects/{project_id}/site/publications", response_model=list[PublicationOut])
async def list_publications(project_id: int, db: DbSession, user: CurrentUser):
    """Everything published for this project, newest first."""
    service = PublicationService(db)
    return [await _out(service, p) for p in await service.list_for_project(project_id, user)]


@router.get("/publications", response_model=list[PublicationOut])
async def list_all_publications(db: DbSession, user: CurrentUser):
    """
    Everything published anywhere, for the page that lists it.

    Deliberately not scoped to a project. Once a link has been sent to somebody, the
    question stops being "what did I publish from this codebase" and becomes "what is
    out there", and that question has no project in it.
    """
    service = PublicationService(db)
    return [await _out(service, p) for p in await service.list_for_org(user)]


@router.post("/publications/{publication_id}/rotate", response_model=PublicationOut)
async def rotate_link(
    publication_id: int, db: DbSession, user: ManagerUser, request: Request
):
    """Mint a new address. Every link that was ever shared stops working."""
    service = PublicationService(db)
    publication = await service.rotate(publication_id, user)
    await _audit(db, user, request, "site.rotate_link", publication_id)
    await db.commit()
    return await _out(service, publication)


@router.post("/publications/{publication_id}/rollback", response_model=PublicationOut)
async def rollback(publication_id: int, db: DbSession, user: ManagerUser, request: Request):
    """Point the address back at the build before this one."""
    service = PublicationService(db)
    publication = await service.rollback(publication_id, user)
    await _audit(db, user, request, "site.rollback", publication_id)
    await db.commit()
    return await _out(service, publication)


@router.delete("/publications/{publication_id}", response_model=PublicationOut)
async def unpublish(publication_id: int, db: DbSession, user: ManagerUser, request: Request):
    """
    Take it down.

    The link stops resolving and the files are removed. The row survives, because
    what was shared and when it stopped being shared is worth being able to answer.
    """
    service = PublicationService(db)
    publication = await service.unpublish(publication_id, user)
    await _audit(db, user, request, "site.unpublish", publication_id)
    await db.commit()
    return await _out(service, publication)


async def _out(service: PublicationService, publication) -> PublicationOut:
    """
    A publication as the studio reads it, with the two derived fields.

    `url` because a slug is not an address until something joins it to a path, and
    the client should not be the thing that knows the path. The commits because the
    only question worth asking about a published site is whether it still describes
    the code.
    """
    out = PublicationOut.model_validate(publication)
    out.url = f"/published/{publication.slug}/"
    out.project_name = await _project_name(service, publication)
    out.latest_commit, out.is_current = await _staleness(service, publication)
    return out


async def _project_name(service: PublicationService, publication) -> str:
    """
    The codebase a publication came from, without assuming the relationship is loaded.

    The list endpoints eager-load it; a publication that has just been created by
    `prepare` has not, and touching the relationship there is a lazy load, which an
    async session raises on rather than performing. So the loaded case is used when
    it is there and one scalar is fetched when it is not: correct in both places, and
    no N+1 in the one that lists.
    """
    from sqlalchemy import inspect as sa_inspect, select

    from codelith.models.project import Project

    if "project" not in sa_inspect(publication).unloaded:
        return publication.project.name if publication.project else ""

    return (
        await service.db.execute(
            select(Project.name).where(Project.id == publication.project_id)
        )
    ).scalar_one_or_none() or ""


async def _staleness(service: PublicationService, publication) -> tuple[str | None, bool | None]:
    """
    Whether what is published still describes the code, as far as can be known.

    Deliberately not a count of commits. Counting would need the repository, and the
    clone is discarded once the reading is built, so a number here would be invented.
    What *is* knowable is which commit the published pages were written from and which
    commit the newest reading covers, so the studio is given both and says
    "built from 4865c2f, latest reading is a1b2c3d" rather than a figure nobody can
    check.

    `None` for either value means there is nothing to compare: a snapshot spanning
    several commits, or a project that has never been analysed.
    """
    build = publication.current_build
    if build is None or not build.commit_sha:
        return None, None

    from codelith.db.repositories.knowledge.knowledge_base_repo import KnowledgeBaseRepository

    latest = await KnowledgeBaseRepository(service.db).get_latest_usable(publication.project_id)
    if latest is None or not latest.commit_sha:
        return None, None
    return latest.commit_sha, latest.commit_sha == build.commit_sha


async def _audit(db, user, request, action: str, publication_id: int) -> None:
    """One shape for every publishing action, so the log reads consistently."""
    await AuditService(db).log(
        action=action,
        resource_type="publication",
        user_id=user.id,
        resource_id=publication_id,
        ip_address=request.client.host if request.client else None,
        commit=False,
    )


__all__ = ["router"]
