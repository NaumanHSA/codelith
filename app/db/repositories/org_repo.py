from sqlalchemy import select
from app.db.repositories.base import BaseRepository
from app.models.organization import Organization


class OrgRepository(BaseRepository[Organization]):
    model = Organization

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self.session.execute(select(Organization).where(Organization.slug == slug))
        return result.scalar_one_or_none()
