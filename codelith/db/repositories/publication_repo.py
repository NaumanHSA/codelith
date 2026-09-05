"""
Reading and writing published sites.

Two repositories because the tables answer different questions: one is asked "what is
this address serving?" on every request to a published page, the other "what happened
when we built it?" only in the studio.

The serving lookup is the hot one. It resolves a slug to a directory and has to do it
without loading a project, a site or a page, so it selects the columns it needs and
nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from codelith.db.repositories.base import BaseRepository
from codelith.models.publication import (
    BuildStatus,
    DocSitePublication,
    DocSitePublicationBuild,
    PublicationStatus,
)


class PublicationRepository(BaseRepository[DocSitePublication]):
    model = DocSitePublication

    async def get_by_slug(self, slug: str) -> DocSitePublication | None:
        """
        The publication answering a URL, with the build it points at.

        The build is eager-loaded because the caller always needs its `storage_path`,
        and a lazy load on an async session raises rather than loading.
        """
        return (
            await self.session.execute(
                select(DocSitePublication)
                .options(selectinload(DocSitePublication.current_build))
                .where(DocSitePublication.slug == slug)
            )
        ).scalar_one_or_none()

    async def get_for_target(self, site_id: int, target: str) -> DocSitePublication | None:
        """
        The one publication for this target, if it exists.

        Republishing finds itself here. There is at most one row per target by
        constraint, which is what keeps a shared link pointing at the newest build
        instead of accumulating a new address per publish.
        """
        return (
            await self.session.execute(
                select(DocSitePublication)
                .options(selectinload(DocSitePublication.current_build))
                .where(
                    DocSitePublication.site_id == site_id,
                    DocSitePublication.target == target,
                )
            )
        ).scalar_one_or_none()

    async def list_for_project(self, project_id: int) -> Sequence[DocSitePublication]:
        """Every publication for a project, newest first, for the studio's panel."""
        return (
            (
                await self.session.execute(
                    select(DocSitePublication)
                    .options(
                        selectinload(DocSitePublication.current_build),
                        selectinload(DocSitePublication.project),
                    )
                    .where(DocSitePublication.project_id == project_id)
                    .order_by(DocSitePublication.id.desc())
                )
            )
            .scalars()
            .all()
        )

    async def list_for_org(self, org_id: int) -> Sequence[DocSitePublication]:
        """
        Everything published anywhere in an org, newest first.

        The per-project list answers "what have I published from here"; this answers
        "what is out there", which is the only question that matters once links have
        been sent to people. Joined through the project, because a publication has no
        org of its own and should not: it belongs to a site, which belongs to a
        project, which is where org membership is decided.
        """
        from codelith.models.project import Project

        return (
            (
                await self.session.execute(
                    select(DocSitePublication)
                    .join(Project, Project.id == DocSitePublication.project_id)
                    .options(
                        selectinload(DocSitePublication.current_build),
                        selectinload(DocSitePublication.project),
                    )
                    .where(Project.org_id == org_id)
                    .order_by(DocSitePublication.id.desc())
                )
            )
            .scalars()
            .all()
        )

    async def slug_exists(self, slug: str) -> bool:
        return (
            await self.session.execute(
                select(DocSitePublication.id).where(DocSitePublication.slug == slug)
            )
        ).first() is not None


class PublicationBuildRepository(BaseRepository[DocSitePublicationBuild]):
    model = DocSitePublicationBuild

    async def list_for_publication(
        self, publication_id: int, limit: int = 20
    ) -> Sequence[DocSitePublicationBuild]:
        return (
            (
                await self.session.execute(
                    select(DocSitePublicationBuild)
                    .where(DocSitePublicationBuild.publication_id == publication_id)
                    .order_by(DocSitePublicationBuild.id.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def previous_succeeded(
        self, publication_id: int, before_build_id: int
    ) -> DocSitePublicationBuild | None:
        """
        What rollback goes back to.

        Only a build that succeeded, because rolling back onto a failed attempt would
        point the address at a directory that was never finished.
        """
        return (
            await self.session.execute(
                select(DocSitePublicationBuild)
                .where(
                    DocSitePublicationBuild.publication_id == publication_id,
                    DocSitePublicationBuild.id < before_build_id,
                    DocSitePublicationBuild.status == BuildStatus.SUCCEEDED,
                )
                .order_by(DocSitePublicationBuild.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def prunable(
        self, publication_id: int, keep: int
    ) -> Sequence[DocSitePublicationBuild]:
        """
        Builds beyond the retention window, oldest of the survivors excluded.

        Never includes the build a publication currently points at: that is decided
        by the caller, which holds the publication row, because a repository that
        reasons about liveness would need to load one to answer.
        """
        rows = (
            (
                await self.session.execute(
                    select(DocSitePublicationBuild)
                    .where(DocSitePublicationBuild.publication_id == publication_id)
                    .order_by(DocSitePublicationBuild.id.desc())
                )
            )
            .scalars()
            .all()
        )
        return rows[keep:]


__all__ = [
    "BuildStatus",
    "PublicationBuildRepository",
    "PublicationRepository",
    "PublicationStatus",
]
