"""
The first account, so there is something to sign in as.

Idempotent by design: it is run by hand in a checkout and by the container entrypoint
on every start, and the second of those means it has to be safe to run against a
database that already has everything.

The credentials come from the environment so an image can be given real ones without
rebuilding. They default to the pair documented in the README and the compose file,
because a default nobody can find is the same as no default.
"""
import asyncio
import os
import codelith.models  # noqa: F401 — registers all ORM models with SQLAlchemy before any query
from codelith.db.session import AsyncSessionLocal
from codelith.db.repositories.org_repo import OrgRepository
from codelith.db.repositories.user_repo import UserRepository
from codelith.db.repositories.project_repo import ProjectRepository
from codelith.core.security import hash_password


async def main():
    # The schema first. The application creates it in its own lifespan, which has not
    # run when this is invoked from a container entrypoint - so seeding a fresh volume
    # failed on `no such table: organizations`, before anything had a chance to say
    # what was actually wrong.
    from codelith.db.bootstrap import ensure_schema
    from codelith.db.session import engine as _engine

    if await ensure_schema(_engine):
        print("Created the schema.")

    async with AsyncSessionLocal() as db:
        org_repo = OrgRepository(db)
        user_repo = UserRepository(db)
        project_repo = ProjectRepository(db)

        org = await org_repo.get_by_slug("default")
        if not org:
            org = await org_repo.create(name="Default Org", slug="default", plan_tier="free")
            print(f"Created org: {org.name} (id={org.id})")

        email = os.environ.get("CODELITH_ADMIN_EMAIL") or "admin@codelith.dev"
        password = os.environ.get("CODELITH_ADMIN_PASSWORD") or "admin1234"

        user = await user_repo.get_by_email(email)
        if not user:
            user = await user_repo.create(
                email=email,
                password_hash=hash_password(password),
                full_name="Admin User",
                role="admin",
                org_id=org.id,
            )
            # Printed, because an account created by a process nobody watched is one
            # nobody can log in as.
            print(f"Created admin: {user.email} / {password}")
        else:
            print(f"Admin already exists: {user.email}")

        await db.commit()
        print("Seed complete.")

    # Dispose explicitly. aiosqlite runs a thread per connection and the pool holds
    # them open, so without this the work finishes and the process does not exit —
    # which looks exactly like a hang, and did.
    from codelith.db.session import engine

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
