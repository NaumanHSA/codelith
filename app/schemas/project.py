from pydantic import BaseModel


class ProjectSourceCreate(BaseModel):
    source_type: str  # github | gitlab | local | pdf | openapi | markdown
    url_or_path: str
    branch: str | None = None
    config_json: dict = {}


class ProjectSourceOut(BaseModel):
    id: int
    project_id: int
    source_type: str
    url_or_path: str
    branch: str | None
    config_json: dict

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    sources: list[ProjectSourceCreate] = []


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class ProjectOut(BaseModel):
    id: int
    org_id: int
    name: str
    slug: str
    description: str | None
    status: str
    sources: list[ProjectSourceOut] = []

    model_config = {"from_attributes": True}
