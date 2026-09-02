"""
Business logic for the two-phase flow.

Phase 1 (analyse) and Phase 2 (compose) are separate jobs on purpose: the user picks
what to write *after* the codebase has been understood, and the knowledge base is
reused across every document type.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.knowledge.constants import EntityKind, JobType
from codelith.knowledge.roles import suggest_doc_types
from codelith.models.job import Job
from codelith.models.knowledge import KnowledgeBase
from codelith.models.user import User
from codelith.schemas.job import JobConfig, JobCreate
from codelith.schemas.knowledge import (
    DocTypeSuggestion,
    EntityHighlight,
    KnowledgeBaseOut,
    KnowledgeBaseSummary,
    ModuleHighlight,
)
from codelith.services.job_service import JobService
from codelith.services.project_service import ProjectService


class KnowledgeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repos = KnowledgeRepositories.for_session(db)
        self.jobs = JobService(db)
        self.projects = ProjectService(db)

    # ── Phase 1 ───────────────────────────────────────────────────────────────

    async def start_analysis(self, project_id: int, user: User, force: bool = False) -> Job:
        """Queue an analysis job. No document type is chosen at this point."""
        from codelith.workers.tasks.analysis_tasks import run_analysis

        await self.projects.get(project_id, user)  # authorises and 404s

        job = await self.jobs.create(
            project_id,
            JobCreate(config=JobConfig(doc_types=[], output_formats=[])),
            user,
            job_type=JobType.ANALYSIS,
            config_overrides={"force": force},
        )
        task = run_analysis.delay(job.id, force)
        await self.jobs.start(job.id, task.id)
        return await self.jobs.get(job.id)

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def latest_status(self, project_id: int) -> str | None:
        """
        The status of this project's most recent knowledge base, or None if it has
        never been analysed.

        Deliberately not `_current`, which filters to usable builds — the feature
        registry has to tell "never analysed" apart from "analysis running" and
        "analysis failed", and each of those tells the reader to do something
        different.
        """
        kb = (
            await self.db.execute(
                select(KnowledgeBase)
                .where(KnowledgeBase.project_id == project_id)
                .order_by(KnowledgeBase.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return kb.status if kb else None

    async def get_summary(self, project_id: int, user: User) -> KnowledgeBaseSummary | None:
        """
        Everything the "ready to compose?" screen needs in one call.

        Returns None when the project has never been analysed — the UI uses that to
        offer analysis rather than a document-type picker.
        """
        await self.projects.get(project_id, user)

        kb = await self._current(project_id)
        if kb is None:
            return None

        roles = await self.repos.modules.role_breakdown(kb.id)
        entity_kinds = await self.repos.entities.kind_breakdown(kb.id)
        topics = await self.repos.narratives.topics_present(kb.id)
        modules = await self.repos.modules.list_by_kb(kb.id, include_tests=True, limit=1000)
        stats = kb.stats_json or {}

        # Prefer the suggestions computed at build time; recompute if absent (older KB).
        raw = stats.get("suggested_doc_types") or suggest_doc_types(entity_kinds, roles)

        routes = await self.repos.entities.list_by_kind(kb.id, EntityKind.ROUTE, limit=8)
        deps = await self.repos.entities.list_by_kind(kb.id, EntityKind.DEPENDENCY, limit=12)
        entrypoints = await self.repos.entities.list_by_kind(kb.id, EntityKind.ENTRYPOINT, limit=6)

        # Biggest non-test modules with a summary — the ones a reader would recognise.
        highlights = [
            m for m in sorted(modules, key=lambda m: m.loc, reverse=True)
            if not m.is_test
        ][:6]

        return KnowledgeBaseSummary(
            knowledge_base=KnowledgeBaseOut.model_validate(kb),
            module_count=len(modules),
            entity_count=sum(entity_kinds.values()),
            narrative_topics=sorted(topics),
            languages=sorted({m.language for m in modules if m.language}),
            roles=roles,
            entity_kinds=entity_kinds,
            suggested_doc_types=[DocTypeSuggestion(**s) for s in raw],
            top_modules=[
                ModuleHighlight(
                    path=m.path, name=m.name, role=m.role, loc=m.loc, summary=m.summary
                )
                for m in highlights
            ],
            sample_routes=[
                EntityHighlight(
                    kind=EntityKind.ROUTE,
                    name=r.name,
                    detail=(r.data_json or {}).get("handler"),
                )
                for r in routes
            ],
            key_dependencies=[d.name for d in deps],
            entrypoints=[e.name for e in entrypoints],
        )

    async def list_bases(self, project_id: int, user: User) -> list[KnowledgeBase]:
        await self.projects.get(project_id, user)
        return list(await self.repos.bases.list_for_project(project_id))

    async def _current(self, project_id: int) -> KnowledgeBase | None:
        """The KB to show: newest usable, else the newest of any status (e.g. running)."""
        usable = await self.repos.bases.get_latest_usable(project_id)
        if usable is not None:
            return usable
        recent = await self.repos.bases.list_for_project(project_id, limit=1)
        return recent[0] if recent else None
