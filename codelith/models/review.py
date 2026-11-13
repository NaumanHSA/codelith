from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from codelith.db.base import Base
from codelith.db.types import json_column


class ChangeReview(Base):
    """
    One review of a change (`knowledge/review.py`), kept so a review run from a
    terminal or by an agent over MCP can be read in the studio afterwards.

    The whole report is stored as it was produced: a review describes a change against
    the knowledge of the moment, and recomputing it later against a newer reading would
    answer a different question.
    """

    __tablename__ = "change_reviews"
    __table_args__ = (Index("ix_change_reviews_project_created", "project_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    #: The reading it was checked against. Not a foreign key: readings are replaced,
    #: and the review should outlive the one it used.
    kb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: `studio` | `cli` | `mcp`
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="studio")
    #: For MCP, the agent's name; for the CLI, nothing.
    client: Mapped[str | None] = mapped_column(String(120), nullable=True)
    base: Mapped[str] = mapped_column(String(120), nullable=False)
    #: None for a working copy.
    head: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: `clear` | `check` | `stop`
    verdict: Mapped[str] = mapped_column(String(10), nullable=False)
    risk: Mapped[str] = mapped_column(String(12), nullable=False, default="low")
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    report_json: Mapped[dict] = mapped_column(json_column(), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
