"""
Starting a documentation job.

This lived on `KnowledgeService` — the shared service that owns analysis — which meant
the base had to import the documentation site service to queue a compose. That is the
coupling the feature split exists to remove: analysing a codebase and writing documents
from it are different jobs, and only one of them is everybody's.

The service reads the knowledge base and refuses when there is none: composing without
one would silently produce a document written from nothing.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from codelith.config import get_settings
from codelith.core.exceptions import NotFoundError
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.apps.documentation.services.site_service import SiteService
from codelith.knowledge.constants import JobType, KBStatus
from codelith.models.job import Job
from codelith.models.user import User
from codelith.schemas.job import JobConfig, JobCreate
from codelith.schemas.knowledge import ComposeRequest
from codelith.services.job_service import JobService
from codelith.services.project_service import ProjectService


class DocumentationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repos = KnowledgeRepositories.for_session(db)
        self.jobs = JobService(db)
        self.projects = ProjectService(db)

    async def start(
        self, project_id: int, req: ComposeRequest, user: User
    ) -> Job:
        """
        Queue a composition job, writing either site pages or legacy documents.

        Refuses when there is no usable knowledge base — composing without one would
        silently produce a document written from nothing.

        A page scope is resolved *here*, before the job exists, so an unknown slug or
        an over-budget request comes back as a 422 the user can act on rather than as
        a job that fails ten minutes into a Celery worker.
        """
        from codelith.apps.documentation.tasks.composition_tasks import run_composition

        await self.projects.get(project_id, user)

        kb = (
            await self.repos.bases.get_by_id(req.kb_id)
            if req.kb_id
            else await self.repos.bases.get_latest_usable(project_id)
        )
        if kb is None or not KBStatus(kb.status).can_serve_features:
            raise NotFoundError("Knowledge base for project", project_id)

        page_slugs: list[str] = []
        doc_types = req.doc_types
        scope: dict = {"kind": "documents", "labels": list(doc_types)}
        if req.page_slugs:
            sites = SiteService(self.db)
            pages = await sites.resolve_scope(
                project_id,
                req.page_slugs,
                max_pages=get_settings().SITE_MAX_PAGES_PER_JOB,
            )
            page_slugs = [f"{p.section_slug}/{p.slug}" for p in pages]
            # Kept in step so strategy, narrative selection and diagram grounding —
            # all of which key off doc type — still see what is being written.
            doc_types = list(dict.fromkeys(p.doc_type for p in pages))
            scope = await sites.describe_scope(project_id, pages)

        job = await self.jobs.create(
            project_id,
            JobCreate(
                config=JobConfig(
                    doc_types=doc_types,
                    page_slugs=page_slugs,
                    output_formats=req.output_formats,
                    human_review=req.human_review,
                )
            ),
            user,
            job_type=JobType.COMPOSITION,
            config_overrides={"kb_id": kb.id},
            scope=scope,
        )
        task = run_composition.delay(job.id)
        await self.jobs.start(job.id, task.id)
        return await self.jobs.get(job.id)
