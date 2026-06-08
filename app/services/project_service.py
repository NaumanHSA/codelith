from sqlalchemy.ext.asyncio import AsyncSession
from slugify import slugify
from app.core.exceptions import NotFoundError, AuthorizationError
from app.db.repositories.project_repo import ProjectRepository, ProjectSourceRepository
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = ProjectRepository(db)
        self.source_repo = ProjectSourceRepository(db)
        self.db = db

    async def create(self, req: ProjectCreate, user: User) -> Project:
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
        return await self.repo.get_by_id_with_sources(project.id)  # type: ignore[return-value]

    async def get(self, project_id: int, user: User) -> Project:
        project = await self.repo.get_by_id_with_sources(project_id)
        if not project:
            raise NotFoundError("Project", project_id)
        self._check_access(project, user)
        return project

    async def list(self, user: User, limit: int = 50, offset: int = 0) -> list[Project]:
        return await self.repo.list_by_org(user.org_id or 0, limit=limit, offset=offset)

    async def update(self, project_id: int, req: ProjectUpdate, user: User) -> Project:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise NotFoundError("Project", project_id)
        self._check_access(project, user)
        updated = await self.repo.update(
            project_id,
            **{k: v for k, v in req.model_dump().items() if v is not None},
        )
        await self.db.commit()
        return updated  # type: ignore[return-value]

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

    def _check_access(self, project: Project, user: User) -> None:
        if project.org_id != (user.org_id or 0) and user.role != "admin":
            raise AuthorizationError("Access denied to this project")
