"""
Running the checks, and saying honestly what ran.

The order matters and is the whole of Q1: check out the repository, ask the knowledge
base which languages are in it, run the tools that apply to those languages, and
normalise what they say into `Finding`.

**Nothing is interpreted here.** Impact, ranking and coverage are later phases. This
one exists to be wrong in obvious ways rather than subtle ones — if the findings are
not real, everything built on them is decoration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.apps.qa.checkout import checkout
from codelith.apps.qa.findings import Finding, Severity, ToolReport
from codelith.apps.qa.impact import ImpactResolver
from codelith.apps.qa.runner import run_tool
from codelith.apps.qa.tools import ToolSpec, tools_for
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.knowledge.constants import KBStatus
from codelith.models.knowledge import KnowledgeBase

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class QAReport:
    """Everything one run produced, including what it could not do."""

    project_id: int
    kb_id: int
    findings: list[Finding] = field(default_factory=list)
    tools: list[ToolReport] = field(default_factory=list)
    #: Non-empty when the files checked are not the commit the KB describes.
    drift_note: str = ""
    #: Tools that apply to this codebase but are not installed. Named so a reader
    #: knows the difference between "clean" and "nothing looked".
    missing_tools: list[str] = field(default_factory=list)
    #: Kept so the caller can ask for a finding's impact sentence without
    #: reimplementing the phrasing.
    resolver: object | None = None

    def explain(self, finding: Finding) -> str:
        return self.resolver.explain(finding) if self.resolver else ""  # type: ignore[attr-defined]

    @property
    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in Severity}
        for finding in self.findings:
            out[finding.severity.value] += 1
        return out

    @property
    def checked(self) -> bool:
        """Whether anything actually ran. An empty report from nothing running is not
        a clean bill of health, and the UI must be able to tell them apart."""
        return any(report.ran for report in self.tools)


class QAService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repos = KnowledgeRepositories.for_session(db)

    async def run(self, project) -> QAReport:
        """
        Check out, run what applies, bring back findings.

        Raises only when there is nothing to check — no knowledge base, or no source to
        clone. Everything a tool does is reported rather than raised.
        """
        kb = await self._usable_kb(project.id)
        languages = await self._languages(kb.id)
        specs = tools_for(languages)

        report = QAReport(project_id=project.id, kb_id=kb.id)
        if not specs:
            logger.info("qa_no_tools", project_id=project.id, languages=languages)
            report.missing_tools = []
            return report

        async with checkout(project, analysed_sha=kb.commit_sha) as tree:
            report.drift_note = tree.drift_note
            # Sequential, not gathered. Two whole-repository passes over the same
            # files compete for the same disk, and the second was measurably slower
            # run concurrently than after.
            for spec in specs:
                report.tools.append(await self._run_one(spec, tree.path))

        for tool_report in report.tools:
            report.findings.extend(tool_report.findings)
            if not tool_report.ran:
                report.missing_tools.append(tool_report.tool)

        # Q2: reach, then rank by it. Severity alone puts a missing annotation in a
        # throwaway script above an undefined name in the composition workflow.
        resolver = ImpactResolver(self.db, project.id, kb.id)
        await resolver.prepare({f.path for f in report.findings})
        report.findings = [resolver.resolve(f) for f in report.findings]
        report.findings.sort(key=resolver.rank)
        report.resolver = resolver
        logger.info(
            "qa_run_complete",
            project_id=project.id,
            findings=len(report.findings),
            tools=[t.tool for t in report.tools if t.ran],
            missing=report.missing_tools,
        )
        return report

    async def _run_one(self, spec: ToolSpec, root) -> ToolReport:
        result = await run_tool(list(spec.command), cwd=root)
        if not result.ran:
            return ToolReport(
                tool=spec.name,
                unavailable=f"{result.unavailable} Without it you do not see {spec.provides}.",
                duration_seconds=result.duration_seconds,
            )

        try:
            findings = spec.parse(result.stdout, result.stderr)
        except Exception as exc:  # pragma: no cover - a parser must not end the run
            logger.warning("qa_parse_failed", tool=spec.name, error=str(exc))
            return ToolReport(
                tool=spec.name,
                unavailable=f"`{spec.name}` ran but its output could not be read: {exc}",
                duration_seconds=result.duration_seconds,
            )

        root = str(root).replace("\\", "/")
        return ToolReport(
            tool=spec.name,
            findings=[f.relative_to(root) for f in findings],
            duration_seconds=result.duration_seconds,
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _usable_kb(self, project_id: int) -> KnowledgeBase:
        kb = (
            await self.db.execute(
                select(KnowledgeBase)
                .where(KnowledgeBase.project_id == project_id)
                .order_by(KnowledgeBase.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if kb is None:
            raise ValueError(
                "This codebase has not been analysed yet. Quality reads the knowledge "
                "base to work out what a finding touches."
            )
        if not KBStatus(kb.status).can_serve_features:
            raise ValueError(
                f"The knowledge base is {kb.status}. Wait for the analysis to finish."
            )
        return kb

    async def _languages(self, kb_id: int) -> list[str]:
        """Which languages the analysis actually found, so the right tools run."""
        modules = await self.repos.modules.list_by_kb(kb_id, include_tests=True, limit=2000)
        return sorted({m.language for m in modules if m.language})


__all__ = ["QAReport", "QAService"]
