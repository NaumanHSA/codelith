from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from codelith.db.base import Base, TimestampMixin


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # pending | running | awaiting_review | completed | failed | cancelled
    #: `JobType` value — "analysis" builds a knowledge base, "composition" writes docs
    #: from one. Defaults to composition so pre-split jobs keep their meaning.
    job_type: Mapped[str] = mapped_column(
        String(32), default="composition", server_default="composition", nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    config_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    #: What this job was asked to do, in the reader's vocabulary rather than the
    #: pipeline's: `{"kind", "sections": [...], "pages": [...], "labels": [...]}`.
    #: Lets a job list say *"wrote API Reference (3 pages)"* instead of "completed".
    #: Recorded at creation, so it is available before a single page exists and
    #: survives a job that failed — which `doc_pages.job_id` alone would not give.
    scope_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    #: The tail of a composition that stopped at the review gate — written pages,
    #: diagrams, QA verdicts, the plan. Set when the job goes `awaiting_review` and
    #: cleared when it finishes, so a non-null payload means somebody still owes this
    #: job a decision. Holds no live objects: `project` and `sandbox` are re-made on
    #: resume, because resuming should publish against the project as it is now.
    #: `none_as_null` so clearing writes SQL NULL rather than JSON `null` — without
    #: it the column is never NULL again once written, and "find the jobs awaiting a
    #: decision" silently matches every job that ever waited for one.
    resume_state_json: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="jobs")  # type: ignore[name-defined]
    steps: Mapped[list["JobStep"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    logs: Mapped[list["AgentLog"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="job")  # type: ignore[name-defined]


class JobStep(Base, TimestampMixin):
    __tablename__ = "job_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped["Job"] = relationship(back_populates="steps")


class AgentLog(Base, TimestampMixin):
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[str] = mapped_column(String(20), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    extra_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    job: Mapped["Job"] = relationship(back_populates="logs")
