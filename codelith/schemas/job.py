from datetime import datetime

from pydantic import AliasPath, BaseModel, Field, model_validator


class JobConfig(BaseModel):
    doc_types: list[str] = ["architecture", "api", "module"]
    #: Resolved page addresses (`"section/page"`) when this job writes into the
    #: project's documentation site. Empty for the legacy one-document-per-type path.
    page_slugs: list[str] = []
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
    #: Read straight off the eager-loaded relationship. The cross-project job list
    #: would otherwise need one fetch per row just to label anything.
    project_name: str | None = Field(
        default=None, validation_alias=AliasPath("project", "name")
    )
    #: "analysis" builds the knowledge base; "composition" writes documents from one.
    job_type: str = "composition"
    status: str
    config_json: dict
    #: What the job was asked to do, in the reader's vocabulary. Lets a job row say
    #: "wrote API Reference (3 pages)" rather than "composition completed".
    scope_json: dict = Field(default_factory=dict, serialization_alias="scope")
    doc_types: list[str] = []
    output_formats: list[str] = []
    requires_human_review: bool = False
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    steps: list[JobStepOut] = []

    model_config = {"from_attributes": True, "populate_by_name": True}

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


class ReviewPageOut(BaseModel):
    """One page's QA verdict, as a reviewer needs to see it."""

    key: str
    title: str
    approved: bool
    score: float | None = None
    claims_total: int = 0
    claims_passed: int | None = None
    #: Why QA doubted it, when it said. The reviewer's whole job is deciding whether
    #: this is a real problem, so an unexplained rejection is not much use.
    notes: str | None = None


class ReviewOut(BaseModel):
    """
    The state of a held composition.

    `awaiting_review` is the one field the studio branches on; the rest is what it
    renders once it has.
    """

    job_id: int
    status: str
    awaiting_review: bool
    pages_written: int
    flagged_count: int
    pages: list[ReviewPageOut] = []
