"""model registry: what kind of endpoint each one is

An embedding endpoint cannot serve a chat tier and a chat endpoint cannot serve the
embedding one — they answer different calls — and nothing in the stored fields
distinguishes them. Provider, model name, URL and window are identical either way.

Without this the quality tier's dropdown offers the embedding model, and picking it
produces something that refuses every request it is ever sent, from inside a job.

Existing rows are backfilled from the tier they already serve, which is exactly the
evidence needed: anything assigned to `embedding` is an embedding endpoint, and
everything else is a chat one.

Revision ID: b2d5f8c31e44
Revises: a1c4e77b2f10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "b2d5f8c31e44"
down_revision: str | None = "a1c4e77b2f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Added with a server default so existing rows get a value, then backfilled for
    # the ones we can do better than the default for.
    op.add_column(
        "model_configs",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="chat"),
    )
    op.execute(
        """
        UPDATE model_configs SET kind = 'embedding'
         WHERE id IN (
             SELECT model_config_id FROM tier_assignments WHERE tier = 'embedding'
         )
        """
    )


def downgrade() -> None:
    op.drop_column("model_configs", "kind")
