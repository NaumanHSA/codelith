"""QA: the tests the model designed, and what happened when they ran

See `QADesignedTest` in `codelith/models/qa.py`.

Revision ID: d8a1f4c6b2e7
Revises: c5e2a7b9d1f3
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "d8a1f4c6b2e7"
down_revision: str | None = "c5e2a7b9d1f3"
branch_labels = None
depends_on = None

_NOW = sa.text("(CURRENT_TIMESTAMP)")


def upgrade() -> None:
    op.create_table(
        "qa_designed_tests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("qa_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("target_path", sa.Text(), nullable=False),
        sa.Column("target_name", sa.Text(), nullable=False),
        sa.Column("target_line", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(20), nullable=False, server_default="untested"),
        sa.Column("runtime", sa.String(20), nullable=False),
        sa.Column("framework", sa.String(20), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False, server_default=""),
        sa.Column("cases_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("results_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("tries", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("verdict", sa.Text(), nullable=False, server_default=""),
        sa.Column("output", sa.Text(), nullable=False, server_default=""),
        sa.Column("finding_fingerprint", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
    )
    op.create_index("ix_qa_designed_tests_run_id", "qa_designed_tests", ["run_id"])
    op.create_index("ix_qa_designed_tests_project_id", "qa_designed_tests", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_qa_designed_tests_project_id", table_name="qa_designed_tests")
    op.drop_index("ix_qa_designed_tests_run_id", table_name="qa_designed_tests")
    op.drop_table("qa_designed_tests")
