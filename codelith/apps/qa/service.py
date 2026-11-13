"""
Starting a QA run, doing it, and reading back what it found.

A run is a job like any other: queued on the worker, its stages written as job steps,
stopped by the same cancellation flag. It checks one reading — the newest usable one
when it starts — through the files that reading kept, so it never needs the checkout
and can run while the code moves on. A reading taken before readings kept their files
has them fetched from git first.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.apps.qa import designed, fixes, impact
from codelith.apps.qa.areas import AREA_IDS, DEPTHS, SEVERITIES, SEVERITY_RANK
from codelith.apps.qa.checks import CHECKS, runs_at
from codelith.apps.qa.checks import flows as flow_checks
from codelith.apps.qa.checks import review as review_checks
from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding, fingerprint_all, quote
from codelith.core.cancellation import CancellationToken
from codelith.core.exceptions import NotFoundError, ValidationError
from codelith.db.repositories.job_repo import JobRepository, JobStepRepository
from codelith.db.repositories.knowledge.knowledge_base_repo import KnowledgeBaseRepository
from codelith.db.repositories.knowledge.source_repo import SourceRepository, StoredFile
from codelith.knowledge.atlas import AtlasService
from codelith.knowledge.compare import CompareService
from codelith.knowledge.constants import JobType
from codelith.models.knowledge import KnowledgeBase
from codelith.models.project import ProjectSource
from codelith.models.qa import QADesignedTest, QAFinding, QAFindingState, QARun
from codelith.models.user import User
from codelith.services.job_service import JobService
from codelith.services.snapshot_service import SnapshotService

logger = structlog.get_logger(__name__)

PREPARE = "qa_prepare"
REPORT = "qa_report"

#: Lines of code shown above and below a finding.
CONTEXT_LINES = 6

#: Written on a line, silences what QA finds on it.
SUPPRESS = "codelith: ignore"


def steps_for(areas: list[str], online: bool = False, depth: str = "quick") -> list[str]:
    """The job steps a run with these areas reports, in order."""
    wanted = set(areas)
    return [PREPARE, *(c.step for c in CHECKS if c.areas & wanted and runs_at(c, depth, online)), REPORT]


def mask(lines: list[str], first: int, masks: list, shown: str | None = None) -> list[str]:
    """Lines starting at line `first`, with every masked span replaced: a secret is never shown."""
    out = list(lines)
    for entry in masks or []:
        try:
            number, start, end = int(entry[0]), int(entry[1]), int(entry[2])
        except (TypeError, ValueError, IndexError):
            continue
        i = number - first
        if 0 <= i < len(out) and 0 <= start < end <= len(out[i]):
            out[i] = out[i][:start] + (shown or "•" * 6) + out[i][end:]
    return out


class QAService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.jobs = JobService(db)

    # -- starting -------------------------------------------------------------------

    async def start(
        self,
        project_id: int,
        user: User,
        *,
        areas: list[str],
        depth: str = "quick",
        scope: dict | None = None,
        online: bool = False,
    ) -> QARun:
        areas = [a for a in AREA_IDS if a in set(areas)]
        if not areas:
            raise ValidationError("Pick at least one area to check.")
        known = {d.id: d for d in DEPTHS}
        if depth not in known:
            raise ValidationError(f"Unknown depth: {depth}.")
        if not known[depth].available:
            raise ValidationError(f"{known[depth].label} is not available yet. {known[depth].why_not}")
        # Online only means something for the checks that use it.
        online = bool(online) and "dependencies" in areas
        scope = scope or {"kind": "all"}
        if scope.get("kind") not in ("all", "parts", "since", "paths"):
            raise ValidationError("Scope is the whole codebase, some parts, some paths, or what changed since a reading.")

        kb = await KnowledgeBaseRepository(self.db).get_latest_usable(project_id)
        if kb is None:
            raise ValidationError("Read the codebase first: QA checks a reading.")

        job = await JobRepository(self.db).create(
            project_id=project_id,
            created_by=user.id,
            job_type=JobType.QA,
            status="pending",
            config_json={"areas": areas, "depth": depth, "scope": scope, "kb_id": kb.id},
            scope_json={},
        )
        run = QARun(
            project_id=project_id,
            kb_id=kb.id,
            job_id=job.id,
            created_by=user.id,
            areas_json=areas,
            scope_json=scope,
            depth=depth,
            online=online,
            status="queued",
        )
        self.db.add(run)
        await self.db.commit()

        from codelith.apps.qa.tasks import run_qa
        from codelith.workers.dispatch import dispatch

        task_id = dispatch(run_qa, run.id)
        await self.jobs.start(job.id, task_id)
        logger.info("qa_queued", run_id=run.id, job_id=job.id, project_id=project_id, areas=areas)
        return run

    async def cancel(self, project_id: int, run_id: int, user: User) -> QARun:
        run = await self.get_run(project_id, run_id)
        if run.job_id and run.status in ("queued", "running"):
            await self.jobs.cancel(run.job_id)
        return run

    # -- doing ----------------------------------------------------------------------

    async def _step(self, job_id: int | None, name: str, status: str, output: dict | None = None) -> None:
        if not job_id:
            return
        repo = JobStepRepository(self.db)
        timing: dict = {}
        if status == "running":
            timing["started_at"] = datetime.now(UTC)
        elif status in ("completed", "failed"):
            timing["completed_at"] = datetime.now(UTC)
        existing = await repo.list(job_id=job_id, agent_name=name)
        if existing:
            for step in existing:
                await repo.update(step.id, status=status, output_json=output or {}, **timing)
        else:
            await repo.create(job_id=job_id, agent_name=name, status=status, input_json={}, output_json=output or {}, **timing)
        await self.db.commit()

    async def _log(self, job_id: int | None, message: str, level: str = "info") -> None:
        if job_id:
            await self.jobs.write_log(job_id, "qa", level, message)

    async def execute(self, run_id: int, token: CancellationToken | None = None) -> QARun:
        run = await self.db.get(QARun, run_id)
        if run is None:
            raise NotFoundError("QA run", run_id)
        run.status = "running"
        await self.db.commit()
        job_id = run.job_id

        await self._step(job_id, PREPARE, "running")
        kb = await self.db.get(KnowledgeBase, run.kb_id) if run.kb_id else None
        if kb is None:
            raise ValidationError("The reading this run was asked to check no longer exists.")
        sources = SourceRepository(self.db)
        if not await sources.has_snapshot(kb.id):
            await self._log(job_id, "This reading was taken before readings kept their files: fetching them from git")
            filled = await SnapshotService(self.db).fill(kb)
            if not filled.ok:
                raise ValidationError(f"QA needs this reading's files, and they could not be fetched: {filled.reason}")
        all_files = await sources.files(kb.id)
        files, scope_note = await self._scope(kb, run.scope_json or {"kind": "all"}, all_files)
        project_sources = list(
            (await self.db.execute(select(ProjectSource).where(ProjectSource.project_id == run.project_id))).scalars()
        )
        ctx = RunContext(
            db=self.db,
            kb=kb,
            areas=frozenset(run.areas_json or []),
            files=files,
            all_files=all_files,
            sources=project_sources,
            token=token,
        )
        await self._log(job_id, f"Checking {len(files)} file(s) of the reading at {(kb.commit_sha or '')[:8]}: {scope_note}")
        await self._step(job_id, PREPARE, "completed", {"files": len(files)})

        found: list[Finding] = []
        # What the checks before found, for the ones after: the designed tests try to
        # reproduce a suspected finding.
        ctx.cache["found"] = found
        ran: list[dict] = []
        for check in CHECKS:
            if not check.areas & ctx.areas or not runs_at(check, run.depth, run.online):
                continue
            await ctx.checkpoint()
            await self._step(job_id, check.step, "running")
            results = await check.run(ctx)
            found += results
            ran.append({"id": check.id, "title": check.title, "found": len(results)})
            await self._log(job_id, f"{check.title}: {len(results)} found")
            await self._step(job_id, check.step, "completed", {"found": len(results)})

        await self._step(job_id, REPORT, "running")
        await self._report(run, kb, ctx, found, ran, scope_note)
        await self._step(job_id, REPORT, "completed", {"findings": len(found)})
        return run

    async def _scope(self, kb: KnowledgeBase, scope: dict, all_files: list[StoredFile]) -> tuple[list[StoredFile], str]:
        kind = scope.get("kind", "all")
        if kind == "parts":
            wanted = set(scope.get("parts") or [])
            atlas = await AtlasService(self.db, kb).build()
            paths = {n.path for n in atlas.nodes if not n.fact and atlas.components[n.component].name in wanted}
            return [f for f in all_files if f.path in paths], f"the parts {', '.join(sorted(wanted))}"
        if kind == "paths":
            prefixes = tuple(p.rstrip("/") for p in scope.get("paths") or [] if p)
            chosen = [f for f in all_files if any(f.path == p or f.path.startswith(p + "/") for p in prefixes)]
            return chosen, f"{len(prefixes)} path(s)"
        if kind == "since":
            before = await self.db.get(KnowledgeBase, int(scope.get("kb_id") or 0))
            if before is None or before.project_id != kb.project_id:
                raise ValidationError("The reading to compare with does not exist.")
            if not await SourceRepository(self.db).has_snapshot(before.id):
                filled = await SnapshotService(self.db).fill(before)
                if not filled.ok:
                    raise ValidationError(f"The earlier reading's files could not be fetched: {filled.reason}")
            changed = {c.path for c in (await CompareService(self.db).files(before, kb)).files if c.status != "removed"}
            return [f for f in all_files if f.path in changed], f"what changed since {(before.commit_sha or '')[:8]}"
        return all_files, "the whole codebase"

    async def _report(
        self, run: QARun, kb: KnowledgeBase, ctx: RunContext, found: list[Finding], ran: list[dict], scope_note: str
    ) -> None:
        # `codelith: ignore` on a line silences what is found on it: the decision is
        # written where the code is, and travels with it.
        suppressed = 0
        kept: list[Finding] = []
        for f in found:
            if f.path and f.line:
                lines = await ctx.lines(f.path)
                if 0 < f.line <= len(lines) and SUPPRESS in lines[f.line - 1]:
                    suppressed += 1
                    continue
            kept.append(f)
        found[:] = review_checks.drop_repeats(flow_checks.merge(kept))
        await fixes.attach(ctx, found)
        for f in found:
            if f.path and f.line:
                lines = await ctx.lines(f.path)
                last = min(f.end_line or f.line, f.line + 7)
                f.snippet = "\n".join(
                    mask(lines[f.line - 1 : last], f.line, f.evidence.get("masks", []), f.evidence.get("shown"))
                ) if lines else quote(lines, f.line, f.end_line)
        fingerprint_all(found)
        await impact.attach(ctx, found)

        # New against the last finished run that looked at the same areas.
        previous = (
            await self.db.execute(
                select(QARun)
                .where(QARun.project_id == run.project_id, QARun.status == "completed", QARun.id != run.id)
                .order_by(desc(QARun.id))
                .limit(1)
            )
        ).scalar_one_or_none()
        fixed = 0
        if previous is not None:
            shared = set(previous.areas_json or []) & set(run.areas_json or [])
            before = {
                (fp, path)
                for fp, path, area in (
                    await self.db.execute(
                        select(QAFinding.fingerprint, QAFinding.path, QAFinding.area).where(QAFinding.run_id == previous.id)
                    )
                ).all()
                if area in shared
            }
            known = {fp for fp, _ in before}
            for f in found:
                f.is_new = f.area in shared and f.fingerprint not in known
            scoped = {x.path for x in ctx.files}
            now = {f.fingerprint for f in found}
            fixed = sum(1 for fp, path in before if fp not in now and (path is None or path in scoped))

        states = dict(
            (
                await self.db.execute(
                    select(QAFindingState.fingerprint, QAFindingState.status).where(
                        QAFindingState.project_id == run.project_id
                    )
                )
            ).all()
        )
        found.sort(key=lambda f: (SEVERITY_RANK.get(f.severity, 9), -int(f.impact.get("reach", 0)), f.path or "", f.line or 0))
        for f in found:
            self.db.add(
                QAFinding(
                    run_id=run.id,
                    project_id=run.project_id,
                    fingerprint=f.fingerprint,
                    rule=f.rule,
                    area=f.area,
                    severity=f.severity,
                    confidence=f.confidence,
                    source=f.source,
                    title=f.title,
                    message=f.message,
                    fix=f.fix,
                    patch=f.patch,
                    path=f.path,
                    line=f.line,
                    end_line=f.end_line,
                    snippet=f.snippet,
                    impact_json=f.impact,
                    evidence_json={k: v for k, v in f.evidence.items()},
                    is_new=f.is_new,
                )
            )
        designed_rows = designed.as_rows(ctx.cache.get("designed", []))
        for row in designed_rows:
            self.db.add(QADesignedTest(run_id=run.id, project_id=run.project_id, **row))
        open_ = [f for f in found if states.get(f.fingerprint) not in ("dismissed", "accepted")]
        run.summary_json = {
            "total": len(found),
            "open": len(open_),
            "by_severity": {s: sum(1 for f in open_ if f.severity == s) for s in SEVERITIES},
            "by_area": dict(Counter(f.area for f in open_)),
            "new": sum(1 for f in found if f.is_new),
            "fixed": fixed,
            "compared_with": previous.id if previous is not None else None,
            "files": len(ctx.files),
            "scope": scope_note,
            "commit": kb.commit_sha,
            "checks": ran,
            "notes": ctx.notes,
            "suppressed": suppressed,
            "designed": dict(Counter(r["outcome"] for r in designed_rows)),
        }
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
        await self.db.commit()

    # -- reading back -----------------------------------------------------------------

    async def get_run(self, project_id: int, run_id: int) -> QARun:
        run = await self.db.get(QARun, run_id)
        if run is None or run.project_id != project_id:
            raise NotFoundError("QA run", run_id)
        return run

    async def runs(self, project_id: int, limit: int = 30) -> list[QARun]:
        rows = await self.db.execute(
            select(QARun).where(QARun.project_id == project_id).order_by(desc(QARun.id)).limit(limit)
        )
        return list(rows.scalars())

    async def steps(self, run: QARun) -> list[dict]:
        if not run.job_id:
            return []
        rows = await JobStepRepository(self.db).list(job_id=run.job_id)
        return [{"name": s.agent_name, "status": s.status} for s in rows]

    async def states(self, project_id: int) -> dict[str, QAFindingState]:
        rows = await self.db.execute(select(QAFindingState).where(QAFindingState.project_id == project_id))
        return {s.fingerprint: s for s in rows.scalars()}

    async def findings(self, project_id: int, run_id: int) -> list[QAFinding]:
        await self.get_run(project_id, run_id)
        rows = await self.db.execute(select(QAFinding).where(QAFinding.run_id == run_id).order_by(QAFinding.id))
        return list(rows.scalars())

    async def finding(self, project_id: int, finding_id: int) -> tuple[QAFinding, list[tuple[int, str]]]:
        """One finding, and the code around it as the reading kept it, secrets masked."""
        finding = await self.db.get(QAFinding, finding_id)
        if finding is None or finding.project_id != project_id:
            raise NotFoundError("Finding", finding_id)
        run = await self.db.get(QARun, finding.run_id)
        context: list[tuple[int, str]] = []
        if run and run.kb_id and finding.path and finding.line:
            text = await SourceRepository(self.db).content(run.kb_id, finding.path)
            if text is not None:
                lines = text.splitlines()
                first = max(1, finding.line - CONTEXT_LINES)
                last = min(len(lines), (finding.end_line or finding.line) + CONTEXT_LINES)
                shown = mask(lines[first - 1 : last], first, (finding.evidence_json or {}).get("masks", []), (finding.evidence_json or {}).get("shown"))
                context = list(zip(range(first, last + 1), shown, strict=False))
        return finding, context

    async def designed(self, project_id: int, run_id: int) -> list[QADesignedTest]:
        """The tests a run designed, in the order it wrote them."""
        await self.get_run(project_id, run_id)
        rows = await self.db.execute(
            select(QADesignedTest).where(QADesignedTest.run_id == run_id).order_by(QADesignedTest.id)
        )
        return list(rows.scalars())

    async def designed_for(self, finding: QAFinding) -> QADesignedTest | None:
        """The designed test that raised or reproduced this finding, if one did."""
        rows = await self.db.execute(
            select(QADesignedTest).where(
                QADesignedTest.run_id == finding.run_id, QADesignedTest.finding_fingerprint == finding.fingerprint
            )
        )
        return rows.scalars().first()

    async def set_state(self, project_id: int, fingerprint: str, status: str, reason: str, user: User) -> QAFindingState | None:
        if status not in ("dismissed", "accepted", "open"):
            raise ValidationError("A finding is dismissed, accepted, or open.")
        existing = (
            await self.db.execute(
                select(QAFindingState).where(
                    QAFindingState.project_id == project_id, QAFindingState.fingerprint == fingerprint
                )
            )
        ).scalar_one_or_none()
        if status == "open":
            if existing is not None:
                await self.db.delete(existing)
            await self.db.commit()
            return None
        if existing is None:
            existing = QAFindingState(project_id=project_id, fingerprint=fingerprint, status=status, reason=reason, user_id=user.id)
            self.db.add(existing)
        else:
            existing.status, existing.reason, existing.user_id = status, reason, user.id
        await self.db.commit()
        return existing


__all__ = ["CONTEXT_LINES", "QAService", "mask", "steps_for"]
