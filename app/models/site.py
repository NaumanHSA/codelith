"""
Documentation site ORM models.

The output of this product used to be *a document per job*: one flat
`content_markdown` per doc type, with sections as `##` headings inside it. These two
tables replace that with **one living site per project**, grown a section at a time.

The split that matters is between the *proposal* and what *exists*:

  * `knowledge_bases.site_map_json` is what analysis thinks the site should contain.
    It is rebuilt on every analysis and is never the source of truth.
  * `doc_sites` / `doc_pages` are what the site actually has. Only
    `SiteService.merge_proposal` moves a proposal into them, and it never deletes.

`DocPage.slug` is the load-bearing column. It is a URL, an internal `[[page-slug]]`
link target and the key the merge matches on, so it is assigned once from the first
title and pinned forever — `app.knowledge.sites` holds the rules that keep it stable.

Versions (phase S6) reuse that shape rather than a second table of pages: a
`DocSiteVersion` is a snapshot, and its pages are ordinary `doc_pages` rows carrying
its `version_id`. `version_id IS NULL` is the live site — the one that gets written
to, gets marked stale, and gets read by default. Everything else is frozen.

That is why uniqueness is two partial indexes rather than one constraint: a NULL
`version_id` does not compare equal to itself in SQL, so a single
`UNIQUE(site_id, version_id, section_slug, slug)` would silently permit two live
pages on the same slug — the one thing the whole design forbids.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.knowledge.constants import PageStatus

if TYPE_CHECKING:
    from app.models.project import Project


class DocSite(Base, TimestampMixin):
    """One documentation site per project."""

    __tablename__ = "doc_sites"
    __table_args__ = (
        # One site per project. Growing a site means adding pages, never rows here.
        UniqueConstraint("project_id", name="uq_doc_site_project"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)

    #: The ordered nav: `[{"slug", "title", "order_index", "pinned"}]`, sections only.
    #: Pages live in `doc_pages` so their status can change without rewriting the tree.
    nav_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    #: Knowledge base whose proposal was last merged in — provenance for the map
    #: itself, distinct from the `kb_id` each page records for its prose.
    kb_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True, index=True
    )

    project: Mapped[Project] = relationship(back_populates="doc_site")
    pages: Mapped[list[DocPage]] = relationship(
        back_populates="site", cascade="all, delete-orphan", passive_deletes=True
    )
    versions: Mapped[list[DocSiteVersion]] = relationship(
        back_populates="site", cascade="all, delete-orphan", passive_deletes=True
    )


class DocSiteVersion(Base, TimestampMixin):
    """
    A frozen snapshot of the site.

    Cut deliberately, at a moment worth naming — a release, a milestone. Its pages
    are ordinary `doc_pages` rows carrying this version's id, which means a reader
    and an export walk the same code whether they are looking at the live site or at
    "v1.2". Nothing here is ever written to again.
    """

    __tablename__ = "doc_site_versions"
    __table_args__ = (
        UniqueConstraint("site_id", "label", name="uq_doc_site_version_label"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("doc_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: What the user called it. Unique per site, because it is how they will ask for it.
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The commit most of its pages were written from, for orientation. Null when the
    #: snapshot spans several.
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The nav as it stood, so a snapshot keeps its own section order and titles.
    nav_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    site: Mapped[DocSite] = relationship(back_populates="versions")


class DocPage(Base, TimestampMixin):
    """
    One `.md` file with a stable slug — the unit the site is built and read in.

    Most pages are `planned`: proposed by analysis, listed in the nav, not yet
    written. Composition fills in `content_markdown` and the provenance columns
    (`job_id`, `kb_id`, `commit_sha`, `source_files_json`) a page at a time.
    """

    __tablename__ = "doc_pages"
    __table_args__ = (
        # Slugs are unique per section, which is what makes `/{section}/{page}`
        # addressable. Two partial indexes, not one constraint: see the module
        # docstring — NULL does not equal NULL, so the live set needs its own.
        Index(
            "ux_doc_pages_live",
            "site_id", "section_slug", "slug",
            unique=True,
            postgresql_where=text("version_id IS NULL"),
        ),
        Index(
            "ux_doc_pages_versioned",
            "site_id", "version_id", "section_slug", "slug",
            unique=True,
            postgresql_where=text("version_id IS NOT NULL"),
        ),
        Index("ix_doc_pages_site_status", "site_id", "status"),
        Index("ix_doc_pages_site_section", "site_id", "section_slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("doc_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Null means the live page — the one that gets written, marked stale and read
    #: by default. A non-null value is a frozen copy inside a snapshot.
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("doc_site_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )

    #: Top-level nav entry this page sits under. A section may hold pages of several
    #: doc types — "Guides" built from `getting_started` and `modules` is legitimate —
    #: so this is deliberately not the same thing as `doc_type`.
    section_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    #: Assigned once, pinned forever. See the module docstring.
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    #: Which narratives and module roles this page is written from.
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    #: One sentence on what this page is for. Carried into the planner's prompt in
    #: S2, where it replaces "invent a structure for this document type".
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), default=PageStatus.PLANNED, nullable=False, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: A hand-reordered or renamed page. The merge respects it: re-analysis may not
    #: undo a user's edit to the nav.
    pinned: Mapped[bool] = mapped_column(default=False, nullable=False)

    content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What this page said before the last rewrite. One generation deep, on purpose:
    #: it exists so a regeneration can be reviewed as a diff rather than as a fresh
    #: blob, which is what turns the product from a generator into a review workflow.
    #: Full history is `doc_site_versions` in S6.
    previous_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── Provenance: what this page was written from ───────────────────────────
    #: Composition job that wrote it. Null while `planned`.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kb_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Source files the page was written from. Diffed against a new commit in S5 to
    #: mark exactly the pages a change made stale.
    source_files_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    #: Anchor files the planner proposed, before anything was written. Kept separate
    #: from `source_files_json`, which records what retrieval actually used.
    key_files_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    #: Why analysis proposed this page, and how sure it was — the same evidence
    #: `suggest_doc_types` attaches to a doc type, one level deeper.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: QA's verdict on *this page*. At document granularity the score was
    #: decorative — one number for twenty pages of prose. Per page it is actionable:
    #: it names which page to look at, and `qa_json` holds the claim checks that
    #: justify it.
    qa_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    qa_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    site: Mapped[DocSite] = relationship(back_populates="pages")

    @property
    def path(self) -> str:
        """The page's address within the site."""
        return f"{self.section_slug}/{self.slug}"


__all__ = ["DocSite", "DocPage", "DocSiteVersion"]
