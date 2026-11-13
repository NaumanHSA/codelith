"""The commits of each codebase, for what changed between two readings

See `SourceCommit` in `codelith/models/source.py`.

Revision ID: e2b7c9d4a1f6
Revises: d8a1f4c6b2e7
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "e2b7c9d4a1f6"
down_revision: str | None = "d8a1f4c6b2e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_commits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sha", sa.String(40), nullable=False),
        sa.Column("parents_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("author", sa.String(200), nullable=False, server_default=""),
        sa.Column("authored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("files_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("project_id", "sha", name="uq_source_commits_project_sha"),
    )
    op.create_index("ix_source_commits_project_id", "source_commits", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_source_commits_project_id", table_name="source_commits")
    op.drop_table("source_commits")
