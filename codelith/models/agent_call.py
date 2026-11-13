from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from codelith.db.base import Base
from codelith.db.types import json_column


class AgentCall(Base):
    """
    One tool call an agent made over MCP.

    The MCP server is a second transport over the knowledge base, and until this
    existed nothing it answered left a trace the studio could show: which agents are
    attached, and what they asked before editing. One row per call, written by the
    server after it answers, and never allowed to fail the call itself.

    `kb_id` and `project_id` are plain integers, not foreign keys: a call names a
    codebase by id and may name one that no longer exists, and the record of what was
    asked should outlive the codebase it was asked about.
    """

    __tablename__ = "agent_calls"
    __table_args__ = (Index("ix_agent_calls_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    #: What the agent called itself in the MCP handshake: "claude-code", "cursor"…
    client: Mapped[str] = mapped_column(String(120), nullable=False, default="unknown")
    tool: Mapped[str] = mapped_column(String(80), nullable=False)
    kb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    #: The arguments, minus the codebase id. Small: a path, a symbol, a question.
    args_json: Mapped[dict] = mapped_column(json_column(), default=dict, nullable=False)
    #: The first line of the answer, so a list of calls says what came back.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
