from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from slugify import slugify
from app.core.exceptions import NotFoundError, AuthorizationError
from app.db.repositories.project_repo import ProjectRepository, ProjectSourceRepository
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectOut, ProjectStats, LatestJobOut


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
        return [self._to_out_light(p) for p in projects]

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
        from app.models.job import Job
        from app.models.document import Document

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
        )
        out.latest_job = LatestJobOut.model_validate(latest_job_row) if latest_job_row else None
        return out

    def _to_out_light(self, project: Project) -> ProjectOut:
        """Lightweight ProjectOut for list view — only source_count to avoid N+1."""
        out = ProjectOut.model_validate(project)
        out.stats = ProjectStats(source_count=len(project.sources))
        return out

    def _check_access(self, project: Project, user: User) -> None:
        if project.org_id != (user.org_id or 0) and user.role != "admin":
            raise AuthorizationError("Access denied to this project")
