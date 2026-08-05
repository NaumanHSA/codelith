from datetime import datetime

from pydantic import BaseModel, Field


class SourceProbeRequest(BaseModel):
    """Check a source is usable before anything is persisted."""

    source_type: str = Field(description="local | github | gitlab | bitbucket")
    url_or_path: str
    branch: str | None = None


class SourceProbeOut(BaseModel):
    ok: bool
    source_type: str
    url_or_path: str
    resolved_path: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    file_count: int = 0
    analysable_files: int = 0
    languages: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


class ProjectCreateWithSource(BaseModel):
    """
    Create a project and its first source in one step.

    The source is fetched and validated first; nothing is written unless it works, so
    a bad URL can no longer leave an empty project behind.
    """

    name: str
    description: str | None = None
    source_type: str
    url_or_path: str
    branch: str | None = None
    config_json: dict | None = None


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
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    sources: list[ProjectSourceCreate] = []


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class ProjectStats(BaseModel):
    source_count: int = 0
    job_count: int = 0
    doc_count: int = 0


class LatestJobOut(BaseModel):
    id: int
    status: str

    model_config = {"from_attributes": True}


class ProjectOut(BaseModel):
    id: int
    org_id: int
    name: str
    slug: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    sources: list[ProjectSourceOut] = []
    stats: ProjectStats | None = None
    latest_job: LatestJobOut | None = None

    model_config = {"from_attributes": True}
