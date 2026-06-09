"""Seed script — creates a default org, admin user, and sample project for dev."""
import asyncio
import app.models  # noqa: F401 — registers all ORM models with SQLAlchemy before any query
from app.db.session import AsyncSessionLocal
from app.db.repositories.org_repo import OrgRepository
from app.db.repositories.user_repo import UserRepository
from app.db.repositories.project_repo import ProjectRepository
from app.core.security import hash_password


async def main():
    async with AsyncSessionLocal() as db:
        org_repo = OrgRepository(db)
        user_repo = UserRepository(db)
        project_repo = ProjectRepository(db)

        org = await org_repo.get_by_slug("default")
        if not org:
            org = await org_repo.create(name="Default Org", slug="default", plan_tier="free")
            print(f"Created org: {org.name} (id={org.id})")

        user = await user_repo.get_by_email("admin@docany.dev")
        if not user:
            user = await user_repo.create(
                email="admin@docany.dev",
                password_hash=hash_password("admin1234"),
                full_name="Admin User",
                role="admin",
                org_id=org.id,
            )
            print(f"Created admin: {user.email} / admin1234")

        await db.commit()
        print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
