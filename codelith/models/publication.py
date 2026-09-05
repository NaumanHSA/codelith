"""
Published documentation sites.

Export hands somebody a ZIP. Publishing gives them a URL: the site built once,
written to disk, served read-only by the API that is already running, and revocable.

Two tables, and the split between them is the whole design.

  * `doc_site_publications` is **an address**. It owns the slug people have shared,
    the target it publishes, and a pointer at whichever build is currently answering.
    Republishing changes what that pointer references; it never changes the address,
    because the address is the thing that was given away.
  * `doc_site_publication_builds` is **an artefact**. One row per attempt, immutable
    once written, each owning a directory of files that is never mutated and never
    moved.

**Nothing on disk is ever renamed.** A build lands in its own directory and becomes
live when `current_build_id` is updated, which is one row write. Rollback points the
same column back. Windows cannot rename a directory while a request holds a file open
inside it, so a staging-and-swap layout would fail exactly when the site is being
read, which is the only time it matters.

**A publication is identified by its target**, `live` or a version label. That single
decision answers the question republishing always raises: the same target replaces
itself and keeps its link, a different version label is a different publication with
its own link, and both stay up. Nothing has to guess.

`content_hash` on the build is what makes publishing idempotent. It digests
everything that can change the output, so a publish request whose hash matches the
live build can be answered without building anything.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from codelith.db.base import Base, TimestampMixin
from codelith.db.types import json_column

if TYPE_CHECKING:
    from codelith.models.project import Project
    from codelith.models.site import DocSite


class PublicationStatus:
    """Where a publication is. Only `LIVE` answers a request."""

    BUILDING = "building"
    LIVE = "live"
    FAILED = "failed"
    UNPUBLISHED = "unpublished"


class BuildStatus:
    """Where one build attempt got to."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: The target that means "the site as it stands", as opposed to a version label.
LIVE_TARGET = "live"


class DocSitePublication(Base, TimestampMixin):
    """One published address for one target of one site."""

    __tablename__ = "doc_site_publications"
    __table_args__ = (
        # One publication per target. Republishing the live site must not accumulate
        # addresses: the link somebody was given has to keep resolving to the newest
        # build, which it cannot do if every publish mints a new row.
        UniqueConstraint("site_id", "target", name="uq_publication_site_target"),
        Index("ix_publications_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[int] = mapped_column(
        ForeignKey("doc_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: `live`, or the label of a `DocSiteVersion`. See the module docstring.
    target: Mapped[str] = mapped_column(String(100), default=LIVE_TARGET, nullable=False)

    #: The URL segment, and the capability. Ends in 128 bits of randomness, so the
    #: address is unguessable and rotating it breaks every link that was ever shared.
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)

    renderer: Mapped[str] = mapped_column(String(32), default="builtin", nullable=False)

    #: `link` means anyone holding the URL can read it, which is what sharing with
    #: somebody who has no account on this machine has to mean.
    visibility: Mapped[str] = mapped_column(String(16), default="link", nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default=PublicationStatus.BUILDING, nullable=False, index=True
    )

    #: The build answering requests. NULL while the first build runs, and after a
    #: take-down. A publication with no current build serves nothing at all rather
    #: than serving something stale.
    current_build_id: Mapped[int | None] = mapped_column(
        ForeignKey("doc_site_publication_builds.id", ondelete="SET NULL"),
        nullable=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unpublished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    project: Mapped[Project] = relationship()
    site: Mapped[DocSite] = relationship()
    current_build: Mapped[DocSitePublicationBuild | None] = relationship(
        foreign_keys=[current_build_id], post_update=True
    )
    builds: Mapped[list[DocSitePublicationBuild]] = relationship(
        back_populates="publication",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="DocSitePublicationBuild.publication_id",
        order_by="DocSitePublicationBuild.id.desc()",
    )


class DocSitePublicationBuild(Base, TimestampMixin):
    """One attempt at building a publication. Never written to twice."""

    __tablename__ = "doc_site_publication_builds"
    __table_args__ = (
        Index("ix_publication_builds_pub_status", "publication_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("doc_site_publications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    #: Digest of everything that can change the output. Equal hashes mean an equal
    #: site, which is how a publish that would change nothing is answered without
    #: building anything.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    renderer: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Bumped when a renderer's output changes, so an upgrade rebuilds rather than
    #: reporting a site that is byte-for-byte older than the code that renders it.
    renderer_version: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default=BuildStatus.RUNNING, nullable=False, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Relative to `STORAGE_DIR`, so the store stays browsable and moving the home
    #: directory does not invalidate every row.
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)

    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bytes_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: The commit the pages were written from, so a published site can say how far
    #: behind the repository it has fallen.
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: What `verify` found: `{"links": n, "assets": n, "external": []}`.
    verify_json: Mapped[dict] = mapped_column(json_column(), default=dict, nullable=False)

    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    publication: Mapped[DocSitePublication] = relationship(
        back_populates="builds", foreign_keys=[publication_id]
    )


__all__ = [
    "BuildStatus",
    "DocSitePublication",
    "DocSitePublicationBuild",
    "LIVE_TARGET",
    "PublicationStatus",
]
