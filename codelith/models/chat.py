"""
Conversations about a codebase.

A thread belongs to a project, because that is what bounds the knowledge base the
answers come from. Asking the same question of two repositories is two threads, and
the model that answers one has never seen the other.

Messages store their token count and, for an answer, the evidence it was built from.
Both are recorded at write time rather than recomputed on read: the context wheel
should be a query, and "what did it answer from" is a property of that moment — the
same question asked after a re-analysis retrieves different evidence.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from codelith.db.base import Base, TimestampMixin


class ChatThread(Base, TimestampMixin):
    """One conversation, about one project."""

    __tablename__ = "chat_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Taken from the first question, so a thread list is readable without opening it.
    title: Mapped[str] = mapped_column(String(200), default="New conversation", nullable=False)
    #: Touched on every message, so the sidebar can order by recency rather than by
    #: creation — a thread returned to is more current than one merely started later.
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )


class ChatMessage(Base, TimestampMixin):
    """One turn. `user` or `assistant`."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    #: Counted with the pipeline's tokenizer at write time, so the context wheel is a
    #: sum over rows rather than a re-tokenisation of the whole conversation.
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: What the answer was built from: `{counts, intents, routed_by, sources}`. Empty
    #: on a user turn. A snapshot, not a live view — re-analysing the project changes
    #: what the same question would retrieve, and this records what it *did*.
    evidence_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    #: Citations that resolved against that evidence, and the ones that did not and
    #: were demoted. Stored so a reader can see the check happened, not only its result.
    citations_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    stripped_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    thread: Mapped[ChatThread] = relationship(back_populates="messages")


__all__ = ["ChatThread", "ChatMessage"]
