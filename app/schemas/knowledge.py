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


class AnalyzeRequest(BaseModel):
    """Phase 1 trigger. Deliberately has no doc-type field."""

    force: bool = Field(
        default=False,
        description="Re-analyse even when a ready knowledge base exists for this commit.",
    )


class ComposeRequest(BaseModel):
    """
    Phase 2 trigger — this is where the document type is finally chosen, once the
    knowledge base exists and can tell the user what is worth writing.
    """

    doc_types: list[str] = Field(default_factory=lambda: ["architecture"], min_length=1)
    output_formats: list[str] = Field(default_factory=lambda: ["markdown"])
    human_review: bool = False
    kb_id: int | None = Field(
        default=None,
        description="Compose from a specific knowledge base. Defaults to the latest usable one.",
    )


__all__ = [
    "KBModuleOut",
    "KBModuleDetail",
    "KBEntityOut",
    "KBNarrativeOut",
    "KnowledgeBaseOut",
    "KnowledgeBaseSummary",
    "DocTypeSuggestion",
    "AnalyzeRequest",
]
