from pydantic import BaseModel


class OrgCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None
    plan_tier: str = "free"


class OrgUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class OrgOut(BaseModel):
    id: int
    name: str
    slug: str
    plan_tier: str
    description: str | None

    model_config = {"from_attributes": True}


class OrgMemberOut(BaseModel):
    id: int
    user_id: int
    org_id: int
    role: str

    model_config = {"from_attributes": True}
