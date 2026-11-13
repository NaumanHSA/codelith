"""How to run a codebase, from the files its newest reading kept."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from codelith.api.v1.atlas import servable_kb
from codelith.dependencies import CurrentUser, DbSession
from codelith.knowledge.runbook import RunbookService
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Runbook"])


class NeedOut(BaseModel):
    what: str
    version: str | None = None
    source: str
    kind: str


class StepOut(BaseModel):
    command: str
    note: str = ""
    source: str


class EnvOut(BaseModel):
    name: str
    declared_in: list[str] = Field(default_factory=list)
    read_in: list[str] = Field(default_factory=list)
    has_default: bool = False
    secret: bool = False
    missing: bool = False


class RunbookOut(BaseModel):
    available: bool
    reason: str = ""
    commit: str | None = None
    needs: list[NeedOut] = Field(default_factory=list)
    install: list[StepOut] = Field(default_factory=list)
    run: list[StepOut] = Field(default_factory=list)
    test: list[StepOut] = Field(default_factory=list)
    container: list[StepOut] = Field(default_factory=list)
    ci: list[StepOut] = Field(default_factory=list)
    env: list[EnvOut] = Field(default_factory=list)
    markdown: str = ""


@router.get("/{project_id}/runbook", response_model=RunbookOut)
async def runbook(project_id: int, db: DbSession, user: CurrentUser) -> RunbookOut:
    """What it needs, how to install, run and test it, and the environment it expects."""
    await ProjectService(db).get(project_id, user)
    book = await RunbookService(db, await servable_kb(db, project_id)).build()

    def steps(items):
        return [StepOut(command=s.command, note=s.note, source=s.source) for s in items]

    return RunbookOut(
        available=book.available,
        reason=book.reason,
        commit=book.commit,
        needs=[NeedOut(what=n.what, version=n.version, source=n.source, kind=n.kind) for n in book.needs],
        install=steps(book.install),
        run=steps(book.run),
        test=steps(book.test),
        container=steps(book.container),
        ci=steps(book.ci),
        env=[
            EnvOut(
                name=e.name,
                declared_in=e.declared_in,
                read_in=e.read_in,
                has_default=e.has_default,
                secret=e.secret,
                missing=e.missing,
            )
            for e in book.env
        ],
        markdown=book.markdown() if book.available else "",
    )
