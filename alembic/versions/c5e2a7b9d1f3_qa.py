"""QA: runs, findings with fingerprints, and decisions about them

See `codelith/models/qa.py`.

Revision ID: c5e2a7b9d1f3
Revises: b3c7e1f9a2d4
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c5e2a7b9d1f3"
down_revision: str | None = "b3c7e1f9a2d4"
branch_labels = None
depends_on = None

_NOW = sa.text("(CURRENT_TIMESTAMP)")


def upgrade() -> None:
    op.create_table(
        "qa_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kb_id", sa.Integer(), sa.ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("areas_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("scope_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("depth", sa.String(20), nullable=False, server_default="quick"),
        sa.Column("online", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("summary_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
    )
    op.create_index("ix_qa_runs_project_id", "qa_runs", ["project_id"])
    op.create_index("ix_qa_runs_kb_id", "qa_runs", ["kb_id"])
    op.create_index("ix_qa_runs_job_id", "qa_runs", ["job_id"])

    op.create_table(
        "qa_findings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("qa_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(40), nullable=False),
        sa.Column("rule", sa.String(80), nullable=False),
        sa.Column("area", sa.String(20), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("confidence", sa.String(10), nullable=False, server_default="confirmed"),
        sa.Column("source", sa.String(10), nullable=False, server_default="rule"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("fix", sa.Text(), nullable=False, server_default=""),
        sa.Column("patch", sa.Text(), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("impact_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_new", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_qa_findings_run_id", "qa_findings", ["run_id"])
    op.create_index("ix_qa_findings_project_id", "qa_findings", ["project_id"])
    op.create_index("ix_qa_findings_run_severity", "qa_findings", ["run_id", "severity"])
    op.create_index("ix_qa_findings_project_fingerprint", "qa_findings", ["project_id", "fingerprint"])

    op.create_table(
        "qa_finding_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.String(40), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("project_id", "fingerprint", name="uq_qa_state_project_fingerprint"),
    )
    op.create_index("ix_qa_finding_states_project_id", "qa_finding_states", ["project_id"])


def downgrade() -> None:
    op.drop_table("qa_finding_states")
    op.drop_table("qa_findings")
    op.drop_table("qa_runs")
