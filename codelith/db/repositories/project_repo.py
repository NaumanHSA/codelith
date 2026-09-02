from sqlalchemy import select
from sqlalchemy.orm import selectinload

from codelith.db.repositories.base import BaseRepository
from codelith.models.project import Project, ProjectSource


class ProjectRepository(BaseRepository[Project]):
    model = Project

    async def get_by_id_with_sources(self, id: int) -> Project | None:
        result = await self.session.execute(
            select(Project).options(selectinload(Project.sources)).where(Project.id == id)
        )
        return result.scalar_one_or_none()

    async def list_by_org(self, org_id: int, limit: int = 50, offset: int = 0) -> list[Project]:
        result = await self.session.execute(
            select(Project)
            .options(selectinload(Project.sources))
            .where(Project.org_id == org_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class ProjectSourceRepository(BaseRepository[ProjectSource]):
    model = ProjectSource
