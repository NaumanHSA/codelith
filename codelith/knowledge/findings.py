"""
What QA found, read for everyone who is not the QA app.

Ask cites findings, MCP serves them (`qa_findings`), the pre-flight lists a file's
before an edit, a review says which a change touches, the guide puts the serious ones
in AGENTS.md, and the map colours files by them. None of that may import the app, so
the tables are read here, in the base — the same reason `reach_weight` lives in
`preflight.py`. Nothing here runs a check or writes a row.

**Which findings are open.** Runs look at different areas, so a finding's run is not
"the last run": for each area, the latest finished run that checked it says what is open
in that area. A finding someone dismissed or accepted is not open.

**What was never checked is said.** `Coverage` names each area, the run and the commit
that checked it last, and the areas nobody has checked — so an answer can say "no run
has looked for that" instead of a reassuring silence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.models.knowledge import KnowledgeBase
from codelith.models.qa import QAFinding, QAFindingState, QARun

#: The areas a run can check, in the order QA shows them. The app owns their full
#: descriptions (`apps/qa/areas.py`); the base needs only the names, and a unit test
#: keeps the two in step.
QA_AREAS: dict[str, str] = {
    "security": "Security",
    "leakage": "Data leakage",
    "dependencies": "Dependencies & compatibility",
    "errors": "Error handling",
    "breaks": "Things that will break",
    "performance": "Performance & concurrency",
    "config": "Configuration & deployment",
    "tests": "Tests",
}
SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "info")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}

#: Words that make a question one QA has an answer to, and the areas they point at.
_QUESTION_WORDS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\b(secur\w*|vulnerab\w*|exploit\w*|attack\w*|inject\w*|xss|csrf|auth\w* bypass|unsafe|cve\w*|owasp)\b"), ("security",)),
    (re.compile(r"\b(leak\w*|secrets?|credentials?|api keys?|tokens? exposed|pii|private data|password\w*)\b"), ("leakage",)),
    (re.compile(r"\b(dependenc\w*|packages?|librar(y|ies)|outdated|versions?|upgrade\w*|licen[cs]e\w*|compatib\w*)\b"), ("dependencies",)),
    (re.compile(r"\b(exception\w*|error handling|swallow\w*|bare except|try/except|catch(es|ing)?)\b"), ("errors",)),
    (re.compile(r"\b(bugs?|buggy|break\w*|crash\w*|broken|fail\w*|wrong|defects?)\b"), ("breaks",)),
    (re.compile(r"\b(perform\w*|slow\w*|blocking|timeouts?|concurren\w*|race conditions?|deadlocks?)\b"), ("performance",)),
    (re.compile(r"\b(docker\w*|deploy\w*|containers?|ci pipeline|ci/cd|misconfig\w*|compose)\b"), ("config",)),
    (re.compile(r"\b(tests?|tested|coverage|untested)\b"), ("tests",)),
    (re.compile(r"\b(issues?|problems?|risks?|risky|quality|qa|code smells?|safe to|what('s| is) wrong)\b"), tuple(QA_AREAS)),
)


def areas_asked(question: str) -> list[str]:
    """The QA areas a question is about, in QA's order; empty when it is about none."""
    lowered = (question or "").lower()
    hit: set[str] = set()
    for pattern, areas in _QUESTION_WORDS:
        if pattern.search(lowered):
            hit.update(areas)
    return [a for a in QA_AREAS if a in hit]


@dataclass(slots=True)
class Known:
    """One open finding, as the rest of Codelith sees it."""

    id: int
    fingerprint: str
    rule: str
    area: str
    severity: str
    confidence: str
    source: str
    title: str
    message: str
    fix: str
    path: str | None
    line: int | None
    end_line: int | None
    patch: str | None
    snippet: str
    run_id: int
    commit: str | None
    is_new: bool

    @property
    def where(self) -> str:
        if not self.path:
            return "(the codebase as a whole)"
        return f"{self.path}:{self.line}" if self.line else self.path

    def brief(self) -> str:
        return (
            f"- [{self.severity}, {self.confidence}] {self.title} — {self.where} "
            f"(QA run #{self.run_id}, finding #{self.id}). Fix: {self.fix}"
        )


@dataclass(slots=True)
class Checked:
    run_id: int
    finished_at: datetime | None
    commit: str | None
    depth: str


@dataclass(slots=True)
class Coverage:
    #: Area to the latest finished run that checked it.
    areas: dict[str, Checked] = field(default_factory=dict)
    #: The commit of the codebase's latest reading, to say when a run is behind it.
    latest_commit: str | None = None

    def checked(self, area: str) -> bool:
        return area in self.areas

    def behind(self, area: str) -> bool:
        """Checked, but at an older reading than the latest."""
        c = self.areas.get(area)
        return c is not None and bool(self.latest_commit) and c.commit != self.latest_commit

    def unchecked(self, areas: list[str] | None = None) -> list[str]:
        return [a for a in (areas or list(QA_AREAS)) if a not in self.areas]

    def brief(self, areas: list[str] | None = None) -> str:
        wanted = areas or list(QA_AREAS)
        lines = []
        for a in wanted:
            c = self.areas.get(a)
            if c is None:
                lines.append(f"- {QA_AREAS[a]}: never checked by QA. Nothing is known about it either way.")
            else:
                when = c.finished_at.strftime("%Y-%m-%d") if c.finished_at else "earlier"
                stale = " — an older reading than the latest" if self.behind(a) else ""
                lines.append(f"- {QA_AREAS[a]}: checked by QA run #{c.run_id} ({c.depth}) on {when}, at {(c.commit or '')[:8]}{stale}.")
        return "\n".join(lines)


def _matches(path: str | None, wanted: str) -> bool:
    if not path:
        return False
    wanted = wanted.strip().strip("/").replace("\\", "/")
    return path == wanted or path.startswith(wanted + "/") or path.endswith("/" + wanted) or PurePosixPath(path).name == wanted


class FindingsReader:
    def __init__(self, db: AsyncSession, project_id: int) -> None:
        self.db = db
        self.project_id = project_id

    async def coverage(self) -> Coverage:
        runs = (
            await self.db.execute(
                select(QARun)
                .where(QARun.project_id == self.project_id, QARun.status == "completed")
                .order_by(desc(QARun.id))
                .limit(60)
            )
        ).scalars().all()
        out = Coverage()
        for run in runs:
            for area in run.areas_json or []:
                if area in QA_AREAS and area not in out.areas:
                    out.areas[area] = Checked(run.id, run.finished_at, (run.summary_json or {}).get("commit"), run.depth)
        latest = (
            await self.db.execute(
                select(KnowledgeBase.commit_sha)
                .where(KnowledgeBase.project_id == self.project_id, KnowledgeBase.status.in_(("ready", "stale")))
                .order_by(desc(KnowledgeBase.id))
                .limit(1)
            )
        ).scalar_one_or_none()
        out.latest_commit = latest
        return out

    async def open(
        self,
        *,
        path: str | None = None,
        areas: list[str] | None = None,
        min_severity: str | None = None,
        limit: int | None = None,
        coverage: Coverage | None = None,
    ) -> list[Known]:
        """Open findings, most severe first; `path` is a file, a folder or a file name."""
        coverage = coverage or await self.coverage()
        wanted = {a: c.run_id for a, c in coverage.areas.items() if not areas or a in areas}
        if not wanted:
            return []
        rows = (
            await self.db.execute(select(QAFinding).where(QAFinding.run_id.in_(set(wanted.values()))))
        ).scalars().all()
        decided = {
            s.fingerprint
            for s in (
                await self.db.execute(
                    select(QAFindingState).where(QAFindingState.project_id == self.project_id)
                )
            ).scalars()
            if s.status in ("dismissed", "accepted")
        }
        floor = SEVERITY_RANK.get(min_severity or "info", 4)
        commits = {c.run_id: c.commit for c in coverage.areas.values()}
        seen: set[str] = set()
        out: list[Known] = []
        for f in rows:
            if wanted.get(f.area) != f.run_id or f.fingerprint in decided or f.fingerprint in seen:
                continue
            if SEVERITY_RANK.get(f.severity, 9) > floor or (path and not _matches(f.path, path)):
                continue
            seen.add(f.fingerprint)
            out.append(
                Known(
                    id=f.id, fingerprint=f.fingerprint, rule=f.rule, area=f.area, severity=f.severity,
                    confidence=f.confidence, source=f.source, title=f.title, message=f.message, fix=f.fix,
                    path=f.path, line=f.line, end_line=f.end_line, patch=f.patch, snippet=f.snippet or "", run_id=f.run_id,
                    commit=commits.get(f.run_id), is_new=f.is_new,
                )
            )
        out.sort(key=lambda k: (SEVERITY_RANK.get(k.severity, 9), k.path or "", k.line or 0))
        return out[:limit] if limit else out

    async def by_path(self) -> dict[str, tuple[str, int]]:
        """Each file with open findings: its worst severity and how many."""
        out: dict[str, tuple[str, int]] = {}
        for k in await self.open():
            if not k.path:
                continue
            worst, n = out.get(k.path, (k.severity, 0))
            if SEVERITY_RANK.get(k.severity, 9) < SEVERITY_RANK.get(worst, 9):
                worst = k.severity
            out[k.path] = (worst, n + 1)
        return out


def touching(known: list[Known], path: str, lines: list[tuple[int, int]] | None = None) -> list[Known]:
    """The findings in `path`, and of those, the ones inside any of these line ranges."""
    here = [k for k in known if k.path == path]
    if lines is None:
        return here
    return [k for k in here if k.line and any(a <= k.line <= b or (k.end_line and a <= k.end_line <= b) for a, b in lines)]


__all__ = [
    "QA_AREAS",
    "SEVERITIES",
    "Checked",
    "Coverage",
    "FindingsReader",
    "Known",
    "areas_asked",
    "touching",
]
