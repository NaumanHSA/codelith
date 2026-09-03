"""
The models this installation can talk to, and which one serves each tier.

Configuration used to live in `.env`, which is the right home for a thing one operator
sets once on their own machine and the wrong one for an application people run. A user
who wants to try a different writing model should not be editing a file inside a
container and restarting it.

**Two tables, because they answer two different questions.** `model_configs` is what
is *available* — a library you add to and keep. `tier_assignments` is what is *in use*
— one row per tier, pointing at one of them. Keeping them apart is what makes
switching cheap: three configured quality models and a dropdown, rather than editing
the one set of fields in place and losing what was there before.

`ondelete="RESTRICT"` on the assignment: deleting a model that a tier is using would
leave the tier pointing at nothing, and the first thing to notice would be a job
failing. The service refuses the delete and says which tier is holding it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from codelith.db.base import Base
from codelith.db.types import json_column


class ModelConfig(Base):
    """One endpoint this installation knows how to call."""

    __tablename__ = "model_configs"
    __table_args__ = (
        # A label is how a person picks one out of a dropdown, so two models sharing
        # one is a menu you cannot choose from.
        UniqueConstraint("label", name="uq_model_config_label"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    #: What the operator called it. Shown in the tier dropdowns.
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    #: `openai` | `anthropic` | `local`. Decides which of the fields below matter —
    #: see `codelith/llm/providers.py`, where the same split is enforced.
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The model id as its endpoint names it.
    model: Mapped[str] = mapped_column(String(200), nullable=False)

    #: `chat` | `embedding`. Stored, because nothing else can tell them apart: the
    #: fields are identical and only the call differs. Without it the quality tier's
    #: dropdown offers an embedding endpoint, which will simply refuse every request
    #: it is ever sent — and the settings page has no way to know that in advance.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="chat")

    #: `local` only. The two hosted providers have a fixed endpoint, and making it
    #: settable is how an API key once ended up being posted to LM Studio.
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `local` only. Prompts are budgeted against it; a hosted model's window is not
    #: something an operator should have to look up.
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Encrypted at rest, and never returned by the API. See `crypto.py` for what
    #: that is and is not worth: it stops a key being readable in a database file
    #: copied off the machine, and it is not protection from someone who already has
    #: both the file and `APP_SECRET_KEY`.
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: What the last connection test found: `{"ok": bool, "at": iso, "detail": str,
    #: "dimensions": int|null}`. Stored so the settings page can show it without
    #: re-testing every endpoint on every page load.
    last_test_json: Mapped[dict] = mapped_column(json_column(), default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    assignments: Mapped[list[TierAssignment]] = relationship(back_populates="endpoint")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ModelConfig {self.label!r} {self.provider}:{self.model}>"


class TierAssignment(Base):
    """Which configured model serves one tier. Exactly one row per tier."""

    __tablename__ = "tier_assignments"

    #: `quality` | `fast` | `embedding`. The primary key, because a tier has one
    #: answer — "switch the writing model" is an update, never a second row.
    tier: Mapped[str] = mapped_column(String(32), primary_key=True)
    model_config_id: Mapped[int] = mapped_column(
        # RESTRICT rather than CASCADE: deleting a model a tier is using would leave
        # that tier pointing at nothing, and the first sign would be a failed job.
        ForeignKey("model_configs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    #: Named `endpoint`, not `model_config`: that name is reserved in Pydantic v2
    #: and this row is one `from_attributes` away from being surfaced through a schema.
    endpoint: Mapped[ModelConfig] = relationship(back_populates="assignments")


__all__ = ["ModelConfig", "TierAssignment"]
