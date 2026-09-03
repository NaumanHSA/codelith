"""knowledge base: questions worth asking about this codebase

Written while the analysis still has the whole inventory in front of it — modules,
entities, narratives — because that is the only moment anything knows what this
particular repository is about.

The chat page opened with four hardcoded questions, one of which asked a browser SDK
with no database how its database was initialised. Generic suggestions are worse than
none: they advertise that nothing has been read.

Revision ID: c3e9a17d5b28
Revises: b2d5f8c31e44
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c3e9a17d5b28"
down_revision: str | None = "b2d5f8c31e44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "suggested_questions_json",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "suggested_questions_json")
