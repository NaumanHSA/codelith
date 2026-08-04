"""
Business logic for the two-phase flow.

Phase 1 (analyse) and Phase 2 (compose) are separate jobs on purpose: the user picks
what to write *after* the codebase has been understood, and the knowledge base is
reused across every document type.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.constants import JobType, KBStatus
from app.knowledge.roles import suggest_doc_types
from app.models.job import Job
from app.models.knowledge import KnowledgeBase
from app.models.user import User
from app.schemas.job import JobConfig, JobCreate
from app.schemas.knowledge import (
    ComposeRequest,
    DocTypeSuggestion,
    KnowledgeBaseOut,
    KnowledgeBaseSummary,
)
from app.services.job_service import JobService
from app.services.project_service import ProjectService


class KnowledgeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repos = KnowledgeRepositories.for_session(db)
        self.jobs = JobService(db)
        self.projects = ProjectService(db)

    # ── Phase 1 ───────────────────────────────────────────────────────────────

    async def start_analysis(self, project_id: int, user: User, force: bool = False) -> Job:
        """Queue an analysis job. No document type is chosen at this point."""
        from app.workers.tasks.analysis_tasks import run_analysis

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

    # ── Phase 2 ───────────────────────────────────────────────────────────────

    async def start_composition(
        self, project_id: int, req: ComposeRequest, user: User
    ) -> Job:
        """
        Queue a composition job.

        Refuses when there is no usable knowledge base — composing without one would
        silently produce a document written from nothing.
        """
        from app.workers.tasks.composition_tasks import run_composition

        await self.projects.get(project_id, user)

        kb = (
            await self.repos.bases.get_by_id(req.kb_id)
            if req.kb_id
            else await self.repos.bases.get_latest_usable(project_id)
        )
        if kb is None or not KBStatus(kb.status).is_usable:
            raise NotFoundError("Knowledge base for project", project_id)

        job = await self.jobs.create(
            project_id,
            JobCreate(
                config=JobConfig(
                    doc_types=req.doc_types,
                    output_formats=req.output_formats,
                    human_review=req.human_review,
                )
            ),
            user,
            job_type=JobType.COMPOSITION,
            config_overrides={"kb_id": kb.id},
        )
        task = run_composition.delay(job.id)
        await self.jobs.start(job.id, task.id)
        return await self.jobs.get(job.id)

    # ── Reads ─────────────────────────────────────────────────────────────────

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

        return KnowledgeBaseSummary(
            knowledge_base=KnowledgeBaseOut.model_validate(kb),
            module_count=len(modules),
            entity_count=sum(entity_kinds.values()),
            narrative_topics=sorted(topics),
            languages=sorted({m.language for m in modules if m.language}),
            roles=roles,
            entity_kinds=entity_kinds,
            suggested_doc_types=[DocTypeSuggestion(**s) for s in raw],
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
