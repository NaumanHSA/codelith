"""Seed script — creates a default org, admin user, and sample project for dev."""
import asyncio
import codelith.models  # noqa: F401 — registers all ORM models with SQLAlchemy before any query
from codelith.db.session import AsyncSessionLocal
from codelith.db.repositories.org_repo import OrgRepository
from codelith.db.repositories.user_repo import UserRepository
from codelith.db.repositories.project_repo import ProjectRepository
from codelith.core.security import hash_password


async def main():
    async with AsyncSessionLocal() as db:
        org_repo = OrgRepository(db)
        user_repo = UserRepository(db)
        project_repo = ProjectRepository(db)

        org = await org_repo.get_by_slug("default")
        if not org:
            org = await org_repo.create(name="Default Org", slug="default", plan_tier="free")
            print(f"Created org: {org.name} (id={org.id})")

        user = await user_repo.get_by_email("admin@codelith.dev")
        if not user:
            user = await user_repo.create(
                email="admin@codelith.dev",
                password_hash=hash_password("admin1234"),
                full_name="Admin User",
                role="admin",
                org_id=org.id,
            )
            print(f"Created admin: {user.email} / admin1234")

        await db.commit()
        print("Seed complete.")

    # Dispose explicitly. aiosqlite runs a thread per connection and the pool holds
    # them open, so without this the work finishes and the process does not exit —
    # which looks exactly like a hang, and did.
    from codelith.db.session import engine

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
