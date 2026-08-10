"""Pydantic v2 request/response schemas for the Knowledge Base."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.knowledge.constants import EntityKind, KBStatus, ModuleRole, NarrativeTopic


class KBModuleOut(BaseModel):
    id: int
    path: str
    name: str
    kind: str
    role: ModuleRole
    language: str | None = None
    file_count: int = 0
    loc: int = 0
    is_test: bool = False
    summary: str | None = None

    model_config = {"from_attributes": True}


class KBModuleDetail(KBModuleOut):
    symbols_json: list = Field(default_factory=list, serialization_alias="symbols")
    files_json: list = Field(default_factory=list, serialization_alias="files")

    model_config = {"from_attributes": True, "populate_by_name": True}


class KBEntityOut(BaseModel):
    id: int
    kind: EntityKind
    name: str
    data_json: dict = Field(default_factory=dict, serialization_alias="data")
    source_path: str | None = None
    source_line: int | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class KBNarrativeOut(BaseModel):
    id: int
    topic: NarrativeTopic
    content_md: str

    model_config = {"from_attributes": True}


class KnowledgeBaseOut(BaseModel):
    """Status view — what the UI polls while analysis runs."""

    id: int
    project_id: int
    job_id: int | None = None
    commit_sha: str | None = None
    status: KBStatus
    schema_version: int = 1
    stats_json: dict = Field(default_factory=dict, serialization_alias="stats")
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class DocTypeSuggestion(BaseModel):
    """
    A document type worth offering, with the evidence behind it.

    Phase 2 asks the user what to write *after* analysis, so the choices can be
    driven by what was actually found rather than a fixed list.
    """

    doc_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class ModuleHighlight(BaseModel):
    """A module worth showing on the knowledge-base card."""

    path: str
    name: str
    role: ModuleRole
    loc: int = 0
    summary: str | None = None


class EntityHighlight(BaseModel):
    """One extracted fact, shown as evidence of what analysis found."""

    kind: EntityKind
    name: str
    detail: str | None = None


class KnowledgeBaseSummary(BaseModel):
    """Everything the 'ready to compose' screen needs in one call."""

    knowledge_base: KnowledgeBaseOut
    module_count: int = 0
    entity_count: int = 0
    narrative_topics: list[NarrativeTopic] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    roles: dict[str, int] = Field(default_factory=dict)
    entity_kinds: dict[str, int] = Field(default_factory=dict)
    suggested_doc_types: list[DocTypeSuggestion] = Field(default_factory=list)

    # Evidence. Counts alone say "we did something"; these say *what we found*, which
    # is what makes the knowledge base feel real rather than a progress bar that ended.
    top_modules: list[ModuleHighlight] = Field(default_factory=list)
    sample_routes: list[EntityHighlight] = Field(default_factory=list)
    key_dependencies: list[str] = Field(default_factory=list)
    entrypoints: list[str] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    """Phase 1 trigger. Deliberately has no doc-type field."""

    force: bool = Field(
        default=False,
        description="Re-analyse even when a ready knowledge base exists for this commit.",
    )


class AddPageRequest(BaseModel):
    """
    Ask for a page the site does not have.

    Free text, because the reader is describing a gap rather than filling in a form.
    A title may be supplied and is then used verbatim — somebody who named their page
    meant it — otherwise it is derived along with the intent.
    """

    section_slug: str = Field(..., description="Which section of the nav it belongs in.")
    request: str = Field(
        ...,
        min_length=1,
        description="What the page should cover, in the reader's own words.",
    )
    title: str | None = Field(
        default=None,
        description="Optional. Used verbatim when given; derived from the request otherwise.",
    )


class ReviseRequest(BaseModel):
    """
    Change prose that already exists.

    Deliberately not a document type or a plan: the subject is already decided. The
    only inputs are *which* piece and *what should change about it*.
    """

    instructions: str = Field(
        ...,
        min_length=1,
        description="What should change. Free text — this is what the reader typed.",
    )
    anchor: str | None = Field(
        default=None,
        description=(
            "The `anchor_id` of a `##` heading — the id the studio stamps on rendered "
            "headings. Omit to revise the whole page."
        ),
    )


class ComposeRequest(BaseModel):
    """
    Phase 2 trigger — this is where what to write is finally chosen, once the
    knowledge base exists and can tell the user what is worth writing.

    Two scopes, and which one is used decides what the job produces:

      * `page_slugs` — write pages into the project's documentation site. This is
        the path the site is built on.
      * `doc_types` — the original single-document-per-type path, kept working.

    `page_slugs` wins when both are supplied.
    """

    doc_types: list[str] = Field(default_factory=lambda: ["architecture"])
    #: Page addresses (`"api/endpoints"`) or whole sections (`"api"`). A section
    #: writes every page in it that analysis could anchor on real files; an explicit
    #: page address is always honoured.
    page_slugs: list[str] = Field(default_factory=list)
    output_formats: list[str] = Field(default_factory=lambda: ["markdown"])
    human_review: bool = False
    kb_id: int | None = Field(
        default=None,
        description="Compose from a specific knowledge base. Defaults to the latest usable one.",
    )


__all__ = [
    "ModuleHighlight",
    "EntityHighlight",
    "KBModuleOut",
    "KBModuleDetail",
    "KBEntityOut",
    "KBNarrativeOut",
    "KnowledgeBaseOut",
    "KnowledgeBaseSummary",
    "DocTypeSuggestion",
    "AnalyzeRequest",
]


class FeatureOut(BaseModel):
    """
    One thing a codebase unlocks, and whether this project can do it yet.

    `reason` is shown to the reader when the feature is not available, so it says what
    to do rather than what went wrong.
    """

    id: str
    label: str
    blurb: str
    needs: list[str] = Field(default_factory=list)
    route: str
    state: str
    reason: str = ""
