"""page_grounding

Record how much of a page's prose names things the codebase actually contains.

For AI-written documentation this is what makes the rest trustable: without it every
sentence carries the same weight, and a reader cannot tell the paragraph derived from
a function signature from the one a model filled in because the section looked thin.

Stored per page rather than computed on read because it is a property of *this*
generation — the same markdown checked against a later knowledge base would score
differently, and the number a reader saw should be the number that was true when the
page was written.

Revision ID: c3f6a2d84b17
Revises: b2e5f7a91c04
Create Date: 2026-08-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3f6a2d84b17"
down_revision: Union[str, None] = "b2e5f7a91c04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "doc_pages",
        sa.Column(
            "grounding_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("doc_pages", "grounding_json")
