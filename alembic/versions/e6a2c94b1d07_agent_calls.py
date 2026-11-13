"""tool calls agents make over MCP

The MCP server answers agents (Claude Code, Cursor) from the knowledge base and left
no trace the studio could show. One row per call: which client, which tool, which
codebase, and the first line of what came back.

Revision ID: e6a2c94b1d07
Revises: d4f1b2a96c73
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "e6a2c94b1d07"
down_revision: str | None = "d4f1b2a96c73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client", sa.String(length=120), nullable=False, server_default="unknown"),
        sa.Column("tool", sa.String(length=80), nullable=False),
        sa.Column("kb_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("args_json", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_agent_calls_created", "agent_calls", ["created_at"])
    op.create_index("ix_agent_calls_project_id", "agent_calls", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_calls_project_id", table_name="agent_calls")
    op.drop_index("ix_agent_calls_created", table_name="agent_calls")
    op.drop_table("agent_calls")
