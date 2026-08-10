"""
Quality's routes.

One endpoint that runs everything, because the expensive part is the checkout and
splitting the report across four calls would clone four times.

**It is slow and says so.** A QA run clones a repository and runs two whole-repository
passes over it — twenty seconds on a small codebase, minutes on a large one. The
response carries how long each tool took so the studio can be honest about that rather
than showing a spinner that could mean anything.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from codelith.apps.qa.coverage import SurfaceCoverage
from codelith.apps.qa.dependencies import DependencyAudit
from codelith.apps.qa.drift import ArchitectureDrift
from codelith.apps.qa.service import QAService
from codelith.dependencies import CurrentUser, DbSession
from codelith.services.project_service import ProjectService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/projects/{project_id}/quality", tags=["Quality"])


class FindingOut(BaseModel):
    tool: str
    rule: str
    path: str
    line: int
    message: str
    severity: str
    #: The sentence no linter can produce. Empty when there is nothing true to say.
    impact: str = ""
    reached_files: int = 0
    documented_in: list[str] = Field(default_factory=list)


class ToolOut(BaseModel):
    tool: str
    findings: int = 0
    seconds: float = 0.0
    #: Set when the tool could not run. A reader must be able to tell "clean" from
    #: "nothing looked at your code".
    unavailable: str | None = None


class SurfaceOut(BaseModel):
    kind: str
    name: str
    where: str = ""
    named_in: list[str] = Field(default_factory=list)


class DependencyOut(BaseModel):
    issue: str
    package: str
    detail: str = ""
    where: str = ""


class DriftOut(BaseModel):
    source_role: str
    target_role: str
    count: int
    is_new: bool
    summary: str
    examples: list[list[str]] = Field(default_factory=list)


class QualityOut(BaseModel):
    kb_id: int
    #: False when no tool ran at all — an empty findings list then means nothing.
    checked: bool
    counts: dict[str, int] = Field(default_factory=dict)
    findings: list[FindingOut] = Field(default_factory=list)
    tools: list[ToolOut] = Field(default_factory=list)
    #: Non-empty when the files checked are not the commit the KB describes.
    drift_note: str = ""

    coverage_summary: str = ""
    surface: list[SurfaceOut] = Field(default_factory=list)

    dependency_summary: str = ""
    dependencies: list[DependencyOut] = Field(default_factory=list)

    layering_summary: str = ""
    layering: list[DriftOut] = Field(default_factory=list)


#: Findings returned to the studio. The list is ranked, so this is a cut at the tail
#: rather than a sample — nobody scrolls past two hundred, and sending two thousand
#: rows to a browser makes the page the slow part instead of the clone.
_MAX_FINDINGS = 200


@router.post("/run", response_model=QualityOut)
async def run_quality(project_id: int, db: DbSession, user: CurrentUser) -> QualityOut:
    """
    Check this codebase and report what was found.

    A POST rather than a GET: it clones a repository and runs linters over it, which
    is not a read however much the result looks like one.
    """
    from codelith.db.repositories.project_repo import ProjectRepository

    await ProjectService(db).get(project_id, user)  # authorises and 404s
    project = await ProjectRepository(db).get_by_id_with_sources(project_id)

    try:
        report = await QAService(db).run(project)
    except ValueError as exc:
        # No knowledge base, no source, nothing to check — the reader can act on all
        # three, so they are 422 with the sentence rather than a 500.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    coverage = await SurfaceCoverage(db, report.kb_id).measure()
    dependencies = await DependencyAudit(db, report.kb_id, project_id).run()
    layering = await ArchitectureDrift(db, project_id, report.kb_id).run()

    return QualityOut(
        kb_id=report.kb_id,
        checked=report.checked,
        counts=report.counts,
        drift_note=report.drift_note,
        findings=[
            FindingOut(
                tool=f.tool,
                rule=f.rule,
                path=f.path,
                line=f.line,
                message=f.message,
                severity=str(f.severity),
                impact=report.explain(f),
                reached_files=f.impact.reached_files if f.impact else 0,
                documented_in=list(f.impact.documented_in) if f.impact else [],
            )
            for f in report.findings[:_MAX_FINDINGS]
        ],
        tools=[
            ToolOut(
                tool=t.tool,
                findings=len(t.findings),
                seconds=round(t.duration_seconds, 1),
                unavailable=t.unavailable,
            )
            for t in report.tools
        ],
        coverage_summary=coverage.summary,
        surface=[
            SurfaceOut(kind=i.kind, name=i.name, where=i.where, named_in=list(i.named_in))
            for i in coverage.items
        ],
        dependency_summary=dependencies.summary,
        dependencies=[
            DependencyOut(
                issue=str(d.issue), package=d.package, detail=d.detail, where=d.where
            )
            for d in dependencies.findings
        ],
        layering_summary=layering.summary,
        layering=[
            DriftOut(
                source_role=d.source_role,
                target_role=d.target_role,
                count=d.count,
                is_new=d.is_new,
                summary=d.summary,
                examples=[list(pair) for pair in d.examples],
            )
            for d in layering.findings
        ],
    )


__all__ = ["router"]
