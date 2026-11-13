"""
Documentation across every codebase, counted rather than listed.

The studio's Documentation page is a dashboard: how much is written, how much is out
of date, what is published, codebase by codebase. Fetching each codebase's whole site
to count its pages was fine for three codebases and is not for thirty, so the counts
are taken here, in a handful of grouped queries over the live sites (frozen versions
are left out), scoped to the user's organisation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.models.document import Document
from codelith.models.project import Project
from codelith.models.publication import DocSitePublication
from codelith.models.site import DocPage, DocSite, DocSiteVersion
from codelith.models.user import User

#: Statuses whose page has text. `stale` was written and has since fallen behind the
#: code; it still counts as written, which is why it can be out of date.
WRITTEN = ("ready", "stale")


@dataclass(slots=True)
class CodebaseDocs:
    project_id: int
    pages: dict[str, int] = field(default_factory=dict)
    words: int = 0
    last_written_at: datetime | None = None
    versions: int = 0
    documents: int = 0
    #: The live site's publication state, if it has ever been published.
    published: str | None = None
    published_slug: str | None = None

    @property
    def total(self) -> int:
        return sum(n for status, n in self.pages.items() if status != "orphaned")

    @property
    def written(self) -> int:
        return sum(self.pages.get(s, 0) for s in WRITTEN)


class DocumentationOverview:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def for_user(self, user: User) -> list[CodebaseDocs]:
        org = Project.org_id == user.org_id
        out: dict[int, CodebaseDocs] = {}

        def row(pid: int) -> CodebaseDocs:
            return out.setdefault(pid, CodebaseDocs(project_id=pid))

        pages = (
            await self.db.execute(
                select(Project.id, DocPage.status, func.count())
                .join(DocSite, DocSite.project_id == Project.id)
                .join(DocPage, DocPage.site_id == DocSite.id)
                .where(org, DocPage.version_id.is_(None))
                .group_by(Project.id, DocPage.status)
            )
        ).all()
        for pid, status, n in pages:
            row(pid).pages[status] = n

        written = (
            await self.db.execute(
                select(Project.id, func.coalesce(func.sum(DocPage.word_count), 0), func.max(DocPage.updated_at))
                .join(DocSite, DocSite.project_id == Project.id)
                .join(DocPage, DocPage.site_id == DocSite.id)
                .where(org, DocPage.version_id.is_(None), DocPage.status.in_(WRITTEN))
                .group_by(Project.id)
            )
        ).all()
        for pid, words, last in written:
            r = row(pid)
            r.words = int(words or 0)
            r.last_written_at = last

        versions = (
            await self.db.execute(
                select(Project.id, func.count())
                .join(DocSite, DocSite.project_id == Project.id)
                .join(DocSiteVersion, DocSiteVersion.site_id == DocSite.id)
                .where(org)
                .group_by(Project.id)
            )
        ).all()
        for pid, n in versions:
            row(pid).versions = n

        documents = (
            await self.db.execute(
                select(Project.id, func.count())
                .join(Document, Document.project_id == Project.id)
                .where(org)
                .group_by(Project.id)
            )
        ).all()
        for pid, n in documents:
            row(pid).documents = n

        live = (
            await self.db.execute(
                select(Project.id, DocSitePublication.status, DocSitePublication.slug)
                .join(DocSitePublication, DocSitePublication.project_id == Project.id)
                .where(org, DocSitePublication.target == "live")
            )
        ).all()
        for pid, status, slug in live:
            r = row(pid)
            r.published = status
            r.published_slug = slug

        return list(out.values())


__all__ = ["CodebaseDocs", "DocumentationOverview", "WRITTEN"]
