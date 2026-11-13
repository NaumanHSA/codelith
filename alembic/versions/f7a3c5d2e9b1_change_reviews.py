"""reviews of changes, kept for the studio

A change reviewed from a terminal (`codelith review`) or by an agent over MCP
(`review_changes`) is stored with its whole report, so it can be read in the studio
afterwards against the knowledge it was checked with.

Revision ID: f7a3c5d2e9b1
Revises: e6a2c94b1d07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "f7a3c5d2e9b1"
down_revision: str | None = "e6a2c94b1d07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "change_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kb_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="studio"),
        sa.Column("client", sa.String(length=120), nullable=True),
        sa.Column("base", sa.String(length=120), nullable=False),
        sa.Column("head", sa.String(length=120), nullable=True),
        sa.Column("verdict", sa.String(length=10), nullable=False),
        sa.Column("risk", sa.String(length=12), nullable=False, server_default="low"),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_change_reviews_project_created", "change_reviews", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_change_reviews_project_created", table_name="change_reviews")
    op.drop_table("change_reviews")
