"""resize_vector_1024

Change code_chunks.embedding from vector(1536) to vector(1024) to match
text-embedding-bge-m3. Truncates existing rows (incompatible dimensions).

Revision ID: 83eba0dd44dc
Revises: d8ae677c6a7d
Create Date: 2026-06-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = '83eba0dd44dc'
down_revision: Union[str, None] = 'd8ae677c6a7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.config import get_settings
    dims = get_settings().VECTOR_DIMENSIONS  # reads VECTOR_DIMENSIONS from .env

    op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding")
    op.execute("TRUNCATE TABLE code_chunks")
    op.execute(f"ALTER TABLE code_chunks ALTER COLUMN embedding TYPE vector({dims})")
    op.execute(
        "CREATE INDEX ix_code_chunks_embedding ON code_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding")
    op.execute("TRUNCATE TABLE code_chunks")
    op.execute("ALTER TABLE code_chunks ALTER COLUMN embedding TYPE vector(1536)")
    op.execute(
        "CREATE INDEX ix_code_chunks_embedding ON code_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
