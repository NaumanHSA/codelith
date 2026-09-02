"""job_resume_state

Somewhere to put a composition that stopped to ask.

The review gate holds a job between writing and publishing. Holding is easy; coming
back is the part that needs storage, because the worker that paused is not the worker
that resumes — the approval arrives minutes later, over HTTP, in a different process.

What is stored is the tail of the graph's state: the written pages, their diagrams,
the QA verdicts, and the plan they were written against. Deliberately *not* the whole
state — `project`, `job` and `sandbox` are live objects, re-made on resume, and
freezing them would mean resuming against a project as it was rather than as it is.

Nullable, and cleared once the job finishes: a row that still has a payload is a job
still waiting for somebody.

Revision ID: f2b9c41d77ae
Revises: d4a7b1e93c26
Create Date: 2026-08-31
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2b9c41d77ae"
down_revision: str | None = "d4a7b1e93c26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("resume_state_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "resume_state_json")
