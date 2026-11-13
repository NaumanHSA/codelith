"""Documentation across every codebase, for the studio's Documentation dashboard."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from codelith.apps.documentation.services.overview_service import DocumentationOverview
from codelith.dependencies import CurrentUser, DbSession

router = APIRouter(prefix="/documentation", tags=["Documentation"])


class CodebaseDocsOut(BaseModel):
    project_id: int
    #: Page status → count, live site only.
    pages: dict[str, int] = Field(default_factory=dict)
    total: int
    written: int
    words: int
    last_written_at: datetime | None
    versions: int
    documents: int
    published: str | None
    published_slug: str | None


@router.get("/overview", response_model=list[CodebaseDocsOut])
async def overview(db: DbSession, user: CurrentUser) -> list[CodebaseDocsOut]:
    """Per codebase: pages by state, words written, frozen versions, single documents,
    and whether the live site is published. Codebases with none of these are absent."""
    rows = await DocumentationOverview(db).for_user(user)
    return [
        CodebaseDocsOut(
            project_id=r.project_id,
            pages=r.pages,
            total=r.total,
            written=r.written,
            words=r.words,
            last_written_at=r.last_written_at,
            versions=r.versions,
            documents=r.documents,
            published=r.published,
            published_slug=r.published_slug,
        )
        for r in rows
    ]
