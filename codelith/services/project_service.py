# Deferred annotations are load-bearing here: this class defines a method named
# `list`, which shadows the builtin for every annotation evaluated after it.
from __future__ import annotations

import structlog
from slugify import slugify
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.core.exceptions import AuthorizationError, NotFoundError
from codelith.db.repositories.project_repo import ProjectRepository, ProjectSourceRepository
from codelith.memory.graph_store import GraphStore
from codelith.models.project import Project
from codelith.models.user import User
from codelith.schemas.project import (
    LatestJobOut,
    ProjectCreate,
    ProjectOut,
    ProjectStats,
    ProjectUpdate,
)

logger = structlog.get_logger(__name__)


class ProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = ProjectRepository(db)
        self.source_repo = ProjectSourceRepository(db)
        self.db = db

    async def create(self, req: ProjectCreate, user: User) -> ProjectOut:
        slug = slugify(req.name)
        project = await self.repo.create(
            org_id=user.org_id or 0,
            created_by=user.id,
            name=req.name,
            slug=slug,
            description=req.description,
        )
        for src in req.sources:
            await self.source_repo.create(
                project_id=project.id,
                source_type=src.source_type,
                url_or_path=src.url_or_path,
                branch=src.branch,
                config_json=src.config_json,
            )
        await self.db.commit()
        project = await self.repo.get_by_id_with_sources(project.id)
        return await self._to_out(project)  # type: ignore[arg-type]

    async def get(self, project_id: int, user: User) -> ProjectOut:
        project = await self.repo.get_by_id_with_sources(project_id)
        if not project:
            raise NotFoundError("Project", project_id)
        self._check_access(project, user)
        return await self._to_out(project)

    async def list(self, user: User, limit: int = 50, offset: int = 0) -> list[ProjectOut]:
        projects = await self.repo.list_by_org(user.org_id or 0, limit=limit, offset=offset)
        return await self._to_out_many(projects)

    async def update(self, project_id: int, req: ProjectUpdate, user: User) -> ProjectOut:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise NotFoundError("Project", project_id)
        self._check_access(project, user)
        await self.repo.update(
            project_id,
            **{k: v for k, v in req.model_dump().items() if v is not None},
        )
        await self.db.commit()
        updated = await self.repo.get_by_id_with_sources(project_id)
        return await self._to_out(updated)  # type: ignore[arg-type]

    async def delete(self, project_id: int, user: User) -> None:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise NotFoundError("Project", project_id)
        self._check_access(project, user)
        await self.repo.delete(project_id)
        await self.db.commit()

        # The code graph lives outside Postgres, so no cascade reaches it. Left
        # behind, it would answer questions about a project that no longer exists —
        # and the next project to reuse the id would inherit them. Non-fatal: the
        # project is already gone, and failing here would only make that confusing.
        try:
            async with GraphStore() as graph:
                await graph.clear_project(project_id)
        except Exception as exc:  # pragma: no cover - Neo4j optional
            logger.warning("graph_cleanup_failed", project_id=project_id, error=str(exc))

    async def add_source(self, project_id: int, source_type: str, url_or_path: str, user: User, **kwargs):
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise NotFoundError("Project", project_id)
        self._check_access(project, user)
        src = await self.source_repo.create(
            project_id=project_id,
            source_type=source_type,
            url_or_path=url_or_path,
            **kwargs,
        )
        await self.db.commit()
        return src

    async def delete_source(self, project_id: int, source_id: int, user: User) -> None:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise NotFoundError("Project", project_id)
        self._check_access(project, user)
        deleted = await self.source_repo.delete(source_id)
        if not deleted:
            raise NotFoundError("ProjectSource", source_id)
        await self.db.commit()

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _to_out(self, project: Project) -> ProjectOut:
        """Full ProjectOut with stats + latest_job (3 extra queries — used only on single-get)."""
        from codelith.models.document import Document
        from codelith.models.job import Job

        job_count = await self.db.scalar(
            select(func.count()).select_from(Job).where(Job.project_id == project.id)
        )
        doc_count = await self.db.scalar(
            select(func.count()).select_from(Document).where(Document.project_id == project.id)
        )
        latest_job_row = (
            await self.db.execute(
                select(Job).where(Job.project_id == project.id).order_by(Job.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()

        out = ProjectOut.model_validate(project)
        out.stats = ProjectStats(
            source_count=len(project.sources),
            job_count=int(job_count or 0),
            doc_count=int(doc_count or 0),
            page_count=(await self._page_counts([project.id])).get(project.id, 0),
        )
        out.latest_job = LatestJobOut.model_validate(latest_job_row) if latest_job_row else None
        out.kb_status = (await self._kb_statuses([project.id])).get(project.id)
        out.apps_ready = _apps_ready(out.kb_status)
        return out

    async def _to_out_many(self, projects: list[Project]) -> list[ProjectOut]:
        """
        List view stats in three queries for the whole page, not three per project.

        The previous version filled in `source_count` only and left the job and
        document counts at their zero defaults, so every row in the studio read
        "0 jobs · 0 documents" however much had actually run — and `latest_job`
        was always null, which is what the list uses to show project status.
        """
        from codelith.models.document import Document
        from codelith.models.job import Job

        if not projects:
            return []

        ids = [p.id for p in projects]

        job_counts = dict(
            (
                await self.db.execute(
                    select(Job.project_id, func.count())
                    .where(Job.project_id.in_(ids))
                    .group_by(Job.project_id)
                )
            ).all()
        )
        doc_counts = dict(
            (
                await self.db.execute(
                    select(Document.project_id, func.count())
                    .where(Document.project_id.in_(ids))
                    .group_by(Document.project_id)
                )
            ).all()
        )
        # DISTINCT ON needs the distinct expression to lead the ORDER BY.
        latest_jobs = {
            job.project_id: job
            for job in (
                await self.db.execute(
                    select(Job)
                    .where(Job.project_id.in_(ids))
                    .distinct(Job.project_id)
                    .order_by(Job.project_id, Job.created_at.desc())
                )
            ).scalars()
        }

        page_counts = await self._page_counts(ids)
        kb_statuses = await self._kb_statuses(ids)

        outs: list[ProjectOut] = []
        for project in projects:
            out = ProjectOut.model_validate(project)
            out.stats = ProjectStats(
                source_count=len(project.sources),
                job_count=int(job_counts.get(project.id, 0)),
                doc_count=int(doc_counts.get(project.id, 0)),
                page_count=int(page_counts.get(project.id, 0)),
            )
            latest = latest_jobs.get(project.id)
            out.latest_job = LatestJobOut.model_validate(latest) if latest else None
            out.kb_status = kb_statuses.get(project.id)
            out.apps_ready = _apps_ready(out.kb_status)
            outs.append(out)
        return outs

    async def _page_counts(self, ids: list[int]) -> dict[int, int]:
        """
        Written pages per project, live site only.

        `doc_count` counts rows from the legacy single-shot pipeline, so a project
        whose documentation site was full of pages still reported "0 documents" on
        the dashboard. Versioned rows are excluded: a snapshot is a copy of pages
        already counted, and including them would inflate the number every time
        somebody cut a release.
        """
        from codelith.models.site import DocPage, DocSite

        if not ids:
            return {}
        rows = await self.db.execute(
            select(DocSite.project_id, func.count(DocPage.id))
            .join(DocPage, DocPage.site_id == DocSite.id)
            .where(
                DocSite.project_id.in_(ids),
                DocPage.version_id.is_(None),
                DocPage.status.in_(("ready", "stale")),
            )
            .group_by(DocSite.project_id)
        )
        return {pid: int(n) for pid, n in rows.all()}

    async def _kb_statuses(self, ids: list[int]) -> dict[int, str]:
        """The most recent knowledge base status per project."""
        from codelith.models.knowledge import KnowledgeBase

        if not ids:
            return {}
        rows = await self.db.execute(
            select(KnowledgeBase.project_id, KnowledgeBase.status)
            .where(KnowledgeBase.project_id.in_(ids))
            .distinct(KnowledgeBase.project_id)
            .order_by(KnowledgeBase.project_id, KnowledgeBase.id.desc())
        )
        return {pid: status for pid, status in rows.all()}

    def _check_access(self, project: Project, user: User) -> None:
        if project.org_id != (user.org_id or 0) and user.role != "admin":
            raise AuthorizationError("Access denied to this project")


def _apps_ready(kb_status: str | None) -> bool:
    """
    Whether features can run against this project.

    Wraps `KBStatus.can_serve_features` rather than restating it. Four call sites
    once decided this independently and one had drifted, so the same project could
    offer a feature on one screen and refuse it on another.
    """
    from codelith.knowledge.constants import KBStatus

    if not kb_status:
        return False
    try:
        return KBStatus(kb_status).can_serve_features
    except ValueError:
        return False
