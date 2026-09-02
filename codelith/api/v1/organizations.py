from fastapi import APIRouter

from codelith.core.exceptions import ConflictError, NotFoundError
from codelith.db.repositories.org_repo import OrgRepository
from codelith.dependencies import AdminUser, CurrentUser, DbSession
from codelith.schemas.organization import OrgCreate, OrgOut, OrgUpdate

router = APIRouter(prefix="/organizations", tags=["Organizations"])


@router.post("", response_model=OrgOut, status_code=201)
async def create_org(req: OrgCreate, db: DbSession, user: AdminUser):
    repo = OrgRepository(db)
    if await repo.get_by_slug(req.slug):
        raise ConflictError(f"Organization slug '{req.slug}' already exists")
    org = await repo.create(**req.model_dump())
    await db.commit()
    return org


@router.get("/{org_id}", response_model=OrgOut)
async def get_org(org_id: int, db: DbSession, user: CurrentUser):
    org = await OrgRepository(db).get_by_id(org_id)
    if not org:
        raise NotFoundError("Organization", org_id)
    return org


@router.patch("/{org_id}", response_model=OrgOut)
async def update_org(org_id: int, req: OrgUpdate, db: DbSession, user: AdminUser):
    repo = OrgRepository(db)
    org = await repo.update(org_id, **{k: v for k, v in req.model_dump().items() if v is not None})
    if not org:
        raise NotFoundError("Organization", org_id)
    await db.commit()
    return org
