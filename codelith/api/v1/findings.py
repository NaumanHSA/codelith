"""
What QA found, over HTTP, for pages that are not QA's: the map's Findings switch and
the codebase page. Served from the base (`knowledge/findings.py`) for the same reason
the pre-flight is: it derives nothing, it reads what QA kept.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from codelith.dependencies import CurrentUser, DbSession
from codelith.knowledge.findings import QA_AREAS, SEVERITIES, FindingsReader
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Findings"])


class CheckedOut(BaseModel):
    area: str
    label: str
    run_id: int
    finished_at: datetime | None
    commit: str | None
    #: Checked at an older reading than the latest.
    behind: bool


class FileFindingsOut(BaseModel):
    path: str
    worst: str
    count: int


class FindingsMapOut(BaseModel):
    checked: list[CheckedOut] = Field(default_factory=list)
    #: The areas no finished run has checked.
    unchecked: list[str] = Field(default_factory=list)
    #: Open findings by severity, across every checked area.
    open: dict[str, int] = Field(default_factory=dict)
    files: list[FileFindingsOut] = Field(default_factory=list)


@router.get("/{project_id}/findings", response_model=FindingsMapOut)
async def findings_map(project_id: int, db: DbSession, user: CurrentUser) -> FindingsMapOut:
    """Which areas QA has checked, what is open, and each file's worst open finding."""
    await ProjectService(db).get(project_id, user)
    reader = FindingsReader(db, project_id)
    coverage = await reader.coverage()
    known = await reader.open(coverage=coverage)
    worst: dict[str, tuple[str, int]] = {}
    for k in known:
        if not k.path:
            continue
        sev, n = worst.get(k.path, (k.severity, 0))
        if SEVERITIES.index(k.severity) < SEVERITIES.index(sev):
            sev = k.severity
        worst[k.path] = (sev, n + 1)
    counts = Counter(k.severity for k in known)
    return FindingsMapOut(
        checked=[
            CheckedOut(area=a, label=QA_AREAS[a], run_id=c.run_id, finished_at=c.finished_at, commit=c.commit, behind=coverage.behind(a))
            for a, c in coverage.areas.items()
        ],
        unchecked=coverage.unchecked(),
        open={s: counts[s] for s in SEVERITIES if counts[s]},
        files=[
            FileFindingsOut(path=p, worst=s, count=n)
            for p, (s, n) in sorted(worst.items(), key=lambda kv: (SEVERITIES.index(kv[1][0]), -kv[1][1], kv[0]))
        ],
    )
