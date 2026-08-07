"""kb_strategy_cache

Cache the composition strategy on the knowledge base.

The strategy — audience, tone, whether diagrams are worth drawing — is derived from
the KB's narratives and stats for a given doc type. Nothing about it varies per job,
so composing a section page-by-page paid for the same answer once per page: measured
at ~13s a time against a hosted model, on every single run.

`{doc_type: strategy}` rather than one blob, because a project composes several doc
types against one knowledge base and each gets its own pitch.

Revision ID: b2e5f7a91c04
Revises: a91b6d47c052
Create Date: 2026-08-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2e5f7a91c04"
down_revision: Union[str, None] = "a91b6d47c052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "strategy_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "strategy_json")
