"""
Knowledge Base ORM models.

A `KnowledgeBase` is everything we understand about one project at one commit. It is
built once by the analysis workflow and then read repeatedly by composition — the
point being that choosing a second document type costs no re-analysis.

Nothing here encodes a specific programming language: `language` is a free string
supplied by whichever `LanguageProvider` handled the file, and symbol/entity kinds
come from the neutral vocabularies in `app.languages.taxonomy` and
`app.knowledge.constants`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from codelith.db.base import Base, TimestampMixin
from codelith.db.types import json_column
from codelith.knowledge.constants import KBStatus

if TYPE_CHECKING:
    # Import-time only: SQLAlchemy resolves the relationship from its registry, so a
    # runtime import would create a needless cycle with app.models.project.
    from codelith.models.project import Project


class KnowledgeBase(Base, TimestampMixin):
    """One analysed snapshot of a project, keyed by commit."""

    __tablename__ = "knowledge_bases"
    __table_args__ = (
        # Re-analysing the same commit reuses the existing row instead of duplicating.
        UniqueConstraint("project_id", "commit_sha", name="uq_kb_project_commit"),
        Index("ix_kb_project_status", "project_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Analysis job that produced this KB (kept for tracing; KB outlives the job).
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    #: Commit the analysis ran against. Null for non-git sources (uploads, URLs).
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=KBStatus.PENDING, nullable=False, index=True
    )
    #: Bumped when the analysis pipeline changes shape, so old KBs can be rebuilt.
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    #: Aggregate counts and timings — module/entity/narrative totals, languages seen.
    stats_json: Mapped[dict] = mapped_column(json_column(), default=dict, nullable=False)
    #: The architecture map synthesised during analysis: services, layers, tech stack
    #: and the relations between components. Persisted because composition needs it —
    #: it used to live only in analysis workflow state, so every diagram drawn in phase
    #: two was drawn from an empty map and invented its own components.
    architecture_json: Mapped[dict] = mapped_column(json_column(), default=dict, nullable=False)
    #: The site map *proposed* by this analysis: the sections and pages the evidence
    #: says the project's documentation site should contain. Rebuilt on every
    #: analysis and never the source of truth for what exists — `doc_pages` is that.
    #: Kept here so a proposal can be inspected, diffed and re-merged without
    #: re-running the planner.
    site_map_json: Mapped[dict] = mapped_column(json_column(), default=dict, nullable=False)
    #: Questions worth asking about *this* codebase, written while the analysis still
    #: has the whole inventory in front of it. The chat page used to open with four
    #: hardcoded ones — "How is the database initialised?" asked of a browser SDK with
    #: no database — which is a worse first impression than no suggestions at all,
    #: because it advertises that nothing has been read.
    suggested_questions_json: Mapped[list] = mapped_column(
        json_column(), default=list, nullable=False
    )
    #: Repo-relative path → content digest, for every file this build read. The only
    #: thing that makes per-page staleness exact: on the next commit, a page is out
    #: of date exactly when one of the files it was written from has a different
    #: digest here. Deliberately not a git diff — uploads and local directories have
    #: no commits, and this works for all of them.
    file_hashes_json: Mapped[dict] = mapped_column(json_column(), default=dict, nullable=False)
    #: doc-type key → the composition strategy chosen for it: audience, tone, whether
    #: diagrams are worth drawing.
    #:
    #: Cached here because the strategy is a property of *this knowledge base and this
    #: doc type*, not of a job — it reads the same narratives and the same stats every
    #: time, so a second job on the same KB re-derives an answer it already has. It
    #: lives on the KB rather than in a cache because that is exactly its lifetime: a
    #: new analysis makes a new KB, and the strategy is reconsidered with it.
    strategy_json: Mapped[dict] = mapped_column(json_column(), default=dict, nullable=False)
    #: Why a build ended up DEGRADED or FAILED.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped[Project] = relationship(back_populates="knowledge_bases")
    modules: Mapped[list[KBModule]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan", passive_deletes=True
    )
    entities: Mapped[list[KBEntity]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan", passive_deletes=True
    )
    narratives: Mapped[list[KBNarrative]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_usable(self) -> bool:
        return KBStatus(self.status).is_usable


class KBModule(Base, TimestampMixin):
    """
    A cohesive unit of code and what we understand about it.

    Granularity is decided by the language provider (`LanguageProvider.module_ref_for`),
    so "module" means a Python package, a Go package, or a single file as appropriate.
    """

    __tablename__ = "kb_modules"
    __table_args__ = (
        UniqueConstraint("kb_id", "path", name="uq_kb_module_path"),
        Index("ix_kb_modules_kb_role", "kb_id", "role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kb_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Stable identifier from `ModuleRef.key` — repo-relative, POSIX separators.
    path: Mapped[str] = mapped_column(Text, nullable=False)
    #: Human-facing name from `ModuleRef.name` (e.g. "app.agents").
    name: Mapped[str] = mapped_column(Text, nullable=False)
    #: `ModuleKind` value; provider-decided.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: `ModuleRole` value; inferred during analysis.
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    #: Provider language id. Null for mixed-language modules.
    language: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    loc: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_test: Mapped[bool] = mapped_column(default=False, nullable=False)

    #: Serialised `Symbol.to_dict()` list.
    symbols_json: Mapped[list] = mapped_column(json_column(), default=list, nullable=False)
    #: Repo-relative file paths making up this module.
    files_json: Mapped[list] = mapped_column(json_column(), default=list, nullable=False)

    #: LLM-generated prose. The expensive, reusable part — written once per commit.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="modules")


class KBEntity(Base, TimestampMixin):
    """
    A discrete fact — a route, an env var, a dependency, an entrypoint.

    Extracted deterministically where possible (no LLM), which makes these the
    trustworthy backbone the generated prose is checked against.
    """

    __tablename__ = "kb_entities"
    __table_args__ = (
        Index("ix_kb_entities_kb_kind", "kb_id", "kind"),
        Index("ix_kb_entities_kb_name", "kb_id", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kb_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: `EntityKind` value.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Kind-specific payload — an HTTP route stores method/path/handler, a dependency
    #: stores version/ecosystem. Kept schemaless so new entity kinds need no migration.
    data_json: Mapped[dict] = mapped_column(json_column(), default=dict, nullable=False)

    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_line: Mapped[int | None] = mapped_column(Integer, nullable=True)

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="entities")


class KBNarrative(Base, TimestampMixin):
    """
    Cross-cutting prose generated once and reused by every document type.

    `source_refs_json` records which modules/entities fed the narrative so QA can
    verify claims without re-deriving them.
    """

    __tablename__ = "kb_narratives"
    __table_args__ = (
        UniqueConstraint("kb_id", "topic", name="uq_kb_narrative_topic"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kb_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: `NarrativeTopic` value.
    topic: Mapped[str] = mapped_column(String(48), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs_json: Mapped[dict] = mapped_column(json_column(), default=dict, nullable=False)

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="narratives")


__all__ = ["KnowledgeBase", "KBModule", "KBEntity", "KBNarrative"]
