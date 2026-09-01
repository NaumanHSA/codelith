"""Pydantic v2 schemas for the documentation site."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from codelith.knowledge.constants import PageStatus


class SiteVersionOut(BaseModel):
    """A frozen snapshot of the site, for the version switcher."""

    id: int
    site_id: int
    label: str
    notes: str | None = None
    commit_sha: str | None = None
    page_count: int = 0
    snapshot_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SitePageOut(BaseModel):
    """
    One page of the site, whether or not it has been written yet.

    `planned` pages are returned alongside `ready` ones on purpose: the nav doubles
    as the roadmap for a project's documentation, so the UI can grey them out and
    offer a Generate action rather than hiding what does not exist yet.
    """

    id: int
    section_slug: str
    slug: str
    title: str
    doc_type: str
    intent: str | None = None
    status: PageStatus
    order_index: int = 0
    pinned: bool = False
    word_count: int = 0

    # Provenance — what this page was written from. Null while planned.
    job_id: int | None = None
    kb_id: int | None = None
    commit_sha: str | None = None
    source_files: list = Field(default_factory=list, validation_alias="source_files_json")
    key_files: list = Field(default_factory=list, validation_alias="key_files_json")

    # Why analysis proposed it.
    confidence: float | None = None
    reason: str | None = None

    #: QA's verdict on this page, and the claim checks behind it.
    qa_score: float | None = None
    qa: dict = Field(default_factory=dict, validation_alias="qa_json")

    #: How much of this page names things the codebase actually contains, and the
    #: paragraphs that did not. `{}` on a page written before the check existed, or
    #: by the legacy pipeline, which has no knowledge base to check against.
    grounding: dict = Field(default_factory=dict, validation_alias="grounding_json")

    updated_at: datetime | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class SitePageDetail(SitePageOut):
    """
    One page with its prose.

    Split from `SitePageOut` because the site map is fetched on every nav render
    and a thirty-page site's markdown is megabytes. The reader asks for one page
    at a time.
    """

    content_markdown: str | None = None
    #: What the page said before its last rewrite, so a regeneration can be read as
    #: a diff. Null on a page that has only ever been written once.
    previous_markdown: str | None = None
    #: The section this page sits in, so the reader can label it without also
    #: having to hold the whole map.
    section_title: str | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class SiteSectionOut(BaseModel):
    """A top-level nav entry and the pages under it, in order."""

    slug: str
    title: str
    order_index: int = 0
    pinned: bool = False
    pages: list[SitePageOut] = Field(default_factory=list)


class SiteOut(BaseModel):
    """The whole map with per-page status — one call, enough to draw the nav."""

    id: int
    project_id: int
    title: str
    kb_id: int | None = None
    sections: list[SiteSectionOut] = Field(default_factory=list)
    #: Pages analysis no longer proposes. Never deleted, off the live nav, still
    #: readable — a slug that was once published stays addressable.
    orphaned_pages: list[SitePageOut] = Field(default_factory=list)
    #: `PageStatus` → count, across every page including orphans. This is the
    #: coverage view in numeric form: what is built, planned, stale.
    page_counts: dict[str, int] = Field(default_factory=dict)
    #: The landing page, derived from the map on every read so it cannot go stale.
    #: Prose comes from the overview narrative analysis already wrote; the index of
    #: sections and pages is `sections` above, rendered by the reader.
    home_markdown: str | None = None
    #: The version being read. Null is the live site — the one that gets written to.
    version: str | None = None
    #: Every frozen snapshot, newest first, so the switcher needs no second call.
    versions: list[SiteVersionOut] = Field(default_factory=list)
    updated_at: datetime | None = None


class CreateVersionRequest(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    notes: str | None = None


#: Export targets. `markdown` is the raw page tree; the rest are buildable sites.
#: What the site can be exported as. `docx` is one document rather than a project:
#: it is asked for when somebody wants to send, review or print the docs, and a zip
#: of thirty Word files serves none of those.
EXPORT_FORMATS = ("markdown", "mkdocs", "docusaurus", "html", "docx")


__all__ = [
    "EXPORT_FORMATS",
    "CreateVersionRequest",
    "SiteOut",
    "SiteSectionOut",
    "SitePageOut",
    "SitePageDetail",
    "SiteVersionOut",
]
