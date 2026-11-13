"""the files of each reading, each distinct content stored once

Analysis kept only search chunks, which leave gaps, so no reading could show a whole
file or be compared line by line with another. See `codelith/models/source.py`.

Revision ID: b3c7e1f9a2d4
Revises: a8b4d6e3f0c2
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "b3c7e1f9a2d4"
down_revision: str | None = "a8b4d6e3f0c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_blobs",
        sa.Column("hash", sa.String(64), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lines", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    )
    op.create_table(
        "reading_files",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kb_id", sa.Integer(), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("blob_hash", sa.String(64), nullable=False),
        sa.Column("language", sa.String(50), nullable=True),
        sa.Column("kind", sa.String(20), nullable=True),
        sa.Column("masked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("kb_id", "path", name="uq_reading_files_kb_path"),
    )
    op.create_index("ix_reading_files_kb_id", "reading_files", ["kb_id"])
    op.create_index("ix_reading_files_blob_hash", "reading_files", ["blob_hash"])
    op.create_index("ix_reading_files_kb_kind", "reading_files", ["kb_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_reading_files_kb_kind", table_name="reading_files")
    op.drop_index("ix_reading_files_blob_hash", table_name="reading_files")
    op.drop_index("ix_reading_files_kb_id", table_name="reading_files")
    op.drop_table("reading_files")
    op.drop_table("source_blobs")
