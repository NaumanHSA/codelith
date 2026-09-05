"""
Publishing a site, and everything that can be done to one afterwards.

The decisions live here rather than in the task, because most publish requests never
reach a task. Asking to publish a site that has not changed is answered from the
database, and that answer is the point of the feature: a person who presses Publish
twice should be told nothing moved, not handed a second identical build.

The one rule everything else follows: **a publication is identified by its target.**
`live`, or a version label. Republishing the same target reuses the same row and
therefore the same URL, which is what makes a shared link worth sharing. Publishing a
different version label is a different target and gets its own address, so both stay
up. Nothing has to ask the user which they meant.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.apps.documentation.publishing import paths
from codelith.apps.documentation.publishing.fingerprint import content_hash
from codelith.apps.documentation.publishing.renderers import (
    DEFAULT_RENDERER,
    RENDERERS,
    get_renderer,
)
from codelith.apps.documentation.services.site_service import SiteService
from codelith.core.exceptions import NotFoundError, ValidationError
from codelith.db.repositories.publication_repo import (
    PublicationBuildRepository,
    PublicationRepository,
)
from codelith.db.repositories.site_repo import DocSiteRepository
from codelith.models.publication import (
    BuildStatus,
    DocSitePublication,
    LIVE_TARGET,
    PublicationStatus,
)
from codelith.models.user import User

logger = structlog.get_logger(__name__)

#: How many builds to keep per publication. Enough for a rollback and a look at what
#: came before it; a directory of every build ever made fills a disk quietly.
KEEP_BUILDS = 5


class PublicationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.sites = DocSiteRepository(db)
        self.publications = PublicationRepository(db)
        self.builds = PublicationBuildRepository(db)
        self.site_service = SiteService(db)

    # ── Publishing ────────────────────────────────────────────────────────────

    async def prepare(
        self,
        project_id: int,
        user: User,
        *,
        target: str = LIVE_TARGET,
        renderer: str = DEFAULT_RENDERER,
        force: bool = False,
    ) -> dict:
        """
        Decide whether this publish needs to happen, and set it up if it does.

        Returns either `{"unchanged": True, ...}`, having done nothing, or a
        publication and a build row ready for the task to fill in. The caller
        dispatches only in the second case.
        """
        if renderer not in RENDERERS:
            raise ValidationError(f"Unknown renderer {renderer!r}.")
        ok, why = get_renderer(renderer).available()
        if not ok:
            raise ValidationError(f"The {renderer} renderer cannot run here: {why}")

        # Reads the tree exactly as an export would, so what gets published is what
        # the download would have contained.
        tree = await self.site_service.export_tree(
            project_id, user, None if target == LIVE_TARGET else target
        )
        if tree.is_empty:
            raise ValidationError("There is nothing written to publish yet.")

        site = await self.sites.get_for_project(project_id)
        if site is None:
            raise NotFoundError("Documentation site for project", project_id)

        spec = get_renderer(renderer)
        digest = content_hash(tree, renderer=spec.name, renderer_version=spec.version)

        publication = await self.publications.get_for_target(site.id, target)

        if publication is not None and not force:
            current = publication.current_build
            if (
                publication.status == PublicationStatus.LIVE
                and current is not None
                and current.content_hash == digest
                and current.status == BuildStatus.SUCCEEDED
            ):
                # The whole reason the hash exists. Nothing is dispatched, nothing is
                # written, and the studio can say so rather than producing a second
                # identical directory under a new id.
                return {"unchanged": True, "publication": publication, "build": None}

        if publication is None:
            publication = await self.publications.create(
                project_id=project_id,
                site_id=site.id,
                target=target,
                slug=await self._mint_unique_slug(tree.title or f"project-{project_id}"),
                renderer=renderer,
                visibility="link",
                status=PublicationStatus.BUILDING,
                created_by=user.id,
            )
        else:
            # Keep the address; change what it will serve. A publication that fails
            # to rebuild stays live on its previous build, so status only moves to
            # `building` for one that has nothing to fall back on.
            publication.renderer = renderer
            if publication.status != PublicationStatus.LIVE:
                publication.status = PublicationStatus.BUILDING
            await self.db.flush()

        build = await self.builds.create(
            publication_id=publication.id,
            content_hash=digest,
            renderer=spec.name,
            renderer_version=spec.version,
            status=BuildStatus.RUNNING,
            storage_path="",  # filled once the id exists, below
            commit_sha=_commit_of(tree),
        )
        build.storage_path = paths.build_key(publication.id, build.id)
        await self.db.flush()

        return {"unchanged": False, "publication": publication, "build": build}

    async def _mint_unique_slug(self, title: str) -> str:
        """
        An address nobody else has.

        128 bits makes a collision a non-event, but a unique constraint that fires at
        insert time would surface as a 500 on a publish, so it is checked here where
        it can simply be retried.
        """
        for _ in range(5):
            slug = paths.mint_slug(title)
            if not await self.publications.slug_exists(slug):
                return slug
        raise ValidationError("Could not allocate a unique address for this site.")

    # ── Afterwards ────────────────────────────────────────────────────────────

    async def list_for_project(self, project_id: int, user: User) -> list[DocSitePublication]:
        await self.site_service.projects.get(project_id, user)
        return list(await self.publications.list_for_project(project_id))

    async def get(self, publication_id: int, user: User) -> DocSitePublication:
        pub = await self.publications.get_by_id(publication_id)
        if pub is None:
            raise NotFoundError("Publication", publication_id)
        # Scoped through the project, so a publication id from another org reads as
        # missing rather than as somebody else's site.
        await self.site_service.projects.get(pub.project_id, user)
        return pub

    async def rotate(self, publication_id: int, user: User) -> DocSitePublication:
        """
        Mint a new address and break every link that was ever shared.

        The only way back from having sent a link to the wrong person, short of
        taking the site down entirely.
        """
        pub = await self.get(publication_id, user)
        pub.slug = await self._mint_unique_slug(pub.site.title if pub.site else "site")
        await self.db.commit()
        logger.info("publication_rotated", publication_id=pub.id)
        return pub

    async def unpublish(self, publication_id: int, user: User) -> DocSitePublication:
        """
        Stop serving, and remove the files.

        The row stays. What was shared, and when it stopped being shared, is worth
        keeping; the bytes are not.
        """
        pub = await self.get(publication_id, user)
        pub.status = PublicationStatus.UNPUBLISHED
        pub.current_build_id = None
        pub.unpublished_at = datetime.now(UTC)
        await self.db.commit()

        # After the commit. If deletion fails the site is already unreachable, which
        # is what "take it down" was asked to guarantee.
        removed = paths.remove_tree(paths.publication_dir(pub.id))
        logger.info("publication_unpublished", publication_id=pub.id, files_removed=removed)
        return pub

    async def rollback(self, publication_id: int, user: User) -> DocSitePublication:
        """Point the address back at the build before this one."""
        pub = await self.get(publication_id, user)
        if pub.current_build_id is None:
            raise ValidationError("This site is not published, so there is nothing to roll back.")

        previous = await self.builds.previous_succeeded(pub.id, pub.current_build_id)
        if previous is None:
            raise ValidationError("There is no earlier build to roll back to.")

        pub.current_build_id = previous.id
        pub.status = PublicationStatus.LIVE
        pub.published_at = datetime.now(UTC)
        await self.db.commit()
        logger.info("publication_rolled_back", publication_id=pub.id, build_id=previous.id)
        return pub

    async def prune(self, publication_id: int, keep: int = KEEP_BUILDS) -> int:
        """
        Delete build directories past the retention window.

        Never the live one, whatever the window says. Deletion is best-effort: a
        reader holding a file open on Windows must not fail a publish, and the next
        prune will pass this way again.
        """
        pub = await self.publications.get_by_id(publication_id)
        if pub is None:
            return 0

        removed = 0
        for build in await self.builds.prunable(publication_id, keep):
            if build.id == pub.current_build_id:
                continue
            if paths.remove_tree(paths.build_dir(publication_id, build.id)):
                removed += 1
        return removed


def _commit_of(tree) -> str | None:
    """
    The commit a site was written from, when its pages agree on one.

    A snapshot spanning several commits has no single answer, and inventing one would
    put a false provenance line at the foot of every published page.
    """
    shas = {p.commit_sha for s in tree.sections for p in s.pages if p.commit_sha}
    return shas.pop() if len(shas) == 1 else None


__all__ = ["KEEP_BUILDS", "PublicationService"]
