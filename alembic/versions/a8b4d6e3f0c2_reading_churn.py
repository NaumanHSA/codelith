"""how often each file changed, kept with the reading

Read from git while the checkout exists (it is discarded when the job ends), for the
hotspots and the timeline. See `codelith/knowledge/churn.py`.

Revision ID: a8b4d6e3f0c2
Revises: f7a3c5d2e9b1
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "a8b4d6e3f0c2"
down_revision: str | None = "f7a3c5d2e9b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_bases") as batch:
        batch.add_column(sa.Column("churn_json", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("knowledge_bases") as batch:
        batch.drop_column("churn_json")
