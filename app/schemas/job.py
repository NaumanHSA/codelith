from datetime import datetime
from pydantic import BaseModel


class JobConfig(BaseModel):
    doc_types: list[str] = ["architecture", "api", "module"]
    output_formats: list[str] = ["markdown"]
    include_diagrams: bool = True
    human_review: bool = False
    llm_model: str | None = None


class JobCreate(BaseModel):
    config: JobConfig = JobConfig()


class JobStepOut(BaseModel):
    id: int
    agent_name: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class AgentLogOut(BaseModel):
    id: int
    agent_name: str
    level: str
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: int
    project_id: int
    status: str
    config_json: dict
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    steps: list[JobStepOut] = []

    model_config = {"from_attributes": True}


class JobApproveRequest(BaseModel):
    approved: bool
    comment: str | None = None
