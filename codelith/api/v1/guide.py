"""
The instruction file for coding agents (AGENTS.md / CLAUDE.md), written from the
reading. See `knowledge/guide.py`. Base, not an app: it derives nothing of its own,
and the CLI and the studio both hand it out.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from codelith.api.v1.atlas import servable_kb
from codelith.dependencies import CurrentUser, DbSession
from codelith.knowledge.guide import GuideService
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Agent guide"])


class RecipeOut(BaseModel):
    id: str
    title: str
    lines: list[str]


class AgentGuideOut(BaseModel):
    commit: str | None
    #: The file name it belongs in: `AGENTS.md` or `CLAUDE.md`.
    filename: str
    #: The generated section, between its markers.
    markdown: str
    recipes: list[RecipeOut]


@router.get("/{project_id}/agent-guide", response_model=AgentGuideOut)
async def agent_guide(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    format: str = Query(default="agents", pattern="^(agents|claude)$"),
) -> AgentGuideOut:
    await ProjectService(db).get(project_id, user)
    kb = await servable_kb(db, project_id)
    guide = GuideService(db, kb)
    return AgentGuideOut(
        commit=kb.commit_sha,
        filename="CLAUDE.md" if format == "claude" else "AGENTS.md",
        markdown=await guide.markdown(format),
        recipes=[RecipeOut(id=r.id, title=r.title, lines=r.lines) for r in await guide.recipes()],
    )
