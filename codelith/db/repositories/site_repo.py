"""
Repositories for the documentation site.

Three small tables, one file: `doc_sites` has exactly one row per project and
`doc_site_versions` exists only to be pointed at, so splitting them into a package
would be ceremony.

The rule that runs through all of them: `version_id IS NULL` is the **live** site.
Every read defaults to it, because a frozen snapshot leaking into the set that gets
written to, merged, or marked stale would be silently destructive.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from codelith.db.repositories.base import BaseRepository
from codelith.knowledge.constants import PageStatus
from codelith.models.site import DocPage, DocSite, DocSiteVersion


class DocSiteRepository(BaseRepository[DocSite]):
    model = DocSite

    async def get_for_project(self, project_id: int) -> DocSite | None:
        result = await self.session.execute(
            select(DocSite).where(DocSite.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def get_with_pages(self, project_id: int) -> DocSite | None:
        """
        The site with its **live** pages attached.

        The relationship would happily load frozen snapshot rows too, which would
        put the same slug in the nav several times over and let a merge write to a
        version. Filtered here so no caller has to remember.
        """
        result = await self.session.execute(
            select(DocSite)
            .options(
                selectinload(
                    DocSite.pages.and_(DocPage.version_id.is_(None))
                )
            )
            .where(DocSite.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, project_id: int, title: str) -> DocSite:
        """
        The site for a project, created empty on first use.

        Creation is idempotent by the unique constraint on `project_id`: a second
        analysis finds the existing row rather than starting a parallel site.
        """
        if (site := await self.get_for_project(project_id)) is not None:
            return site
        return await self.create(project_id=project_id, title=title, nav_json=[])


class DocPageRepository(BaseRepository[DocPage]):
    model = DocPage

    async def list_for_site(
        self,
        site_id: int,
        *,
        section_slug: str | None = None,
        statuses: Sequence[str] | None = None,
        version_id: int | None = None,
        limit: int = 500,
    ) -> Sequence[DocPage]:
        """
        Pages in nav order. Section ordering lives on `DocSite.nav_json`, so callers
        that need the full tree group these by `section_slug` against the nav.

        `version_id=None` means the *live* site, not "any version": a frozen
        snapshot must never leak into the set that gets written to or marked stale.
        """
        stmt = select(DocPage).where(
            DocPage.site_id == site_id,
            DocPage.version_id.is_(None)
            if version_id is None
            else DocPage.version_id == version_id,
        )
        if section_slug is not None:
            stmt = stmt.where(DocPage.section_slug == section_slug)
        if statuses:
            stmt = stmt.where(DocPage.status.in_(list(statuses)))
        stmt = stmt.order_by(
            DocPage.section_slug, DocPage.order_index, DocPage.id
        ).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_slug(
        self,
        site_id: int,
        section_slug: str,
        slug: str,
        *,
        version_id: int | None = None,
    ) -> DocPage | None:
        result = await self.session.execute(
            select(DocPage).where(
                DocPage.site_id == site_id,
                DocPage.section_slug == section_slug,
                DocPage.slug == slug,
                DocPage.version_id.is_(None)
                if version_id is None
                else DocPage.version_id == version_id,
            )
        )
        return result.scalar_one_or_none()

    async def mark_orphaned(self, page_ids: Sequence[int]) -> int:
        """
        Retire pages analysis no longer proposes — never delete them.

        A slug is a URL somebody may have bookmarked and an internal link target, so
        the page keeps existing and keeps its content; it simply leaves the live nav.
        """
        if not page_ids:
            return 0
        await self.session.execute(
            update(DocPage)
            .where(DocPage.id.in_(list(page_ids)))
            .values(status=PageStatus.ORPHANED),
            # The merge re-reads these rows immediately afterwards to work out which
            # sections still have live pages. Without the sync it would get the
            # identity-mapped instances back with their pre-update status and keep a
            # dead section in the nav.
            execution_options={"synchronize_session": "fetch"},
        )
        await self.session.flush()
        return len(page_ids)

    async def status_breakdown(self, site_id: int) -> dict[str, int]:
        result = await self.session.execute(
            select(DocPage.status, func.count())
            .where(DocPage.site_id == site_id)
            .group_by(DocPage.status)
        )
        return {status: count for status, count in result.all()}


class DocSiteVersionRepository(BaseRepository[DocSiteVersion]):
    model = DocSiteVersion

    async def list_for_site(self, site_id: int) -> Sequence[DocSiteVersion]:
        """Newest first — a version switcher opens on the most recent snapshot."""
        result = await self.session.execute(
            select(DocSiteVersion)
            .where(DocSiteVersion.site_id == site_id)
            .order_by(DocSiteVersion.created_at.desc())
        )
        return result.scalars().all()

    async def get_by_label(self, site_id: int, label: str) -> DocSiteVersion | None:
        result = await self.session.execute(
            select(DocSiteVersion).where(
                DocSiteVersion.site_id == site_id, DocSiteVersion.label == label
            )
        )
        return result.scalar_one_or_none()


__all__ = [
    "DocSiteRepository",
    "DocPageRepository",
    "DocSiteVersionRepository",
]
