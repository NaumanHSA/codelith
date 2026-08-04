from datetime import datetime

from pydantic import BaseModel, Field, model_validator


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
    agent_name: str = Field(serialization_alias="name")
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None = None
    output_json: dict = {}

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def compute_duration(self) -> "JobStepOut":
        if self.started_at and self.completed_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
        return self


class AgentLogOut(BaseModel):
    id: int
    agent_name: str = Field(serialization_alias="agent")
    level: str
    message: str
    created_at: datetime = Field(serialization_alias="timestamp")
    extra_json: dict = Field(default_factory=dict, serialization_alias="extra")

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: int
    project_id: int
    #: "analysis" builds the knowledge base; "composition" writes documents from one.
    job_type: str = "composition"
    status: str
    config_json: dict
    doc_types: list[str] = []
    output_formats: list[str] = []
    requires_human_review: bool = False
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    steps: list[JobStepOut] = []

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def extract_config_fields(self) -> "JobOut":
        cfg = self.config_json or {}
        self.doc_types = cfg.get("doc_types", [])
        self.output_formats = cfg.get("output_formats", ["markdown"])
        self.requires_human_review = cfg.get("human_review", False)
        return self


class JobApproveRequest(BaseModel):
    approved: bool
    comment: str | None = None
