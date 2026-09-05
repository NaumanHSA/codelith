"""published documentation sites

Export hands somebody a ZIP; publishing gives them a URL. Two tables: an address that
people share, and the immutable builds it points at.

The circular foreign key is deliberate and is why the constraint on
`current_build_id` is added after both tables exist rather than inline. A publication
points at its current build and a build belongs to a publication, which is what makes
activation a single row write and rollback the same write in reverse. Nothing on disk
moves, because Windows cannot rename a directory somebody is reading from.

Revision ID: d4f1b2a96c73
Revises: c3e9a17d5b28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "d4f1b2a96c73"
down_revision: str | None = "c3e9a17d5b28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "doc_site_publications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("target", sa.String(length=100), nullable=False, server_default="live"),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("renderer", sa.String(length=32), nullable=False, server_default="builtin"),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="link"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="building"),
        # No FK yet: the table it references does not exist until the next statement.
        sa.Column("current_build_id", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unpublished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["doc_sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("site_id", "target", name="uq_publication_site_target"),
        sa.UniqueConstraint("slug", name="uq_publication_slug"),
    )
    op.create_index("ix_publications_project", "doc_site_publications", ["project_id"])
    op.create_index(
        "ix_doc_site_publications_slug", "doc_site_publications", ["slug"], unique=True
    )
    op.create_index("ix_doc_site_publications_status", "doc_site_publications", ["status"])

    op.create_table(
        "doc_site_publication_builds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("renderer", sa.String(length=32), nullable=False),
        sa.Column("renderer_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bytes_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("verify_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["publication_id"], ["doc_site_publications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_publication_builds_pub_status",
        "doc_site_publication_builds",
        ["publication_id", "status"],
    )
    op.create_index(
        "ix_doc_site_publication_builds_content_hash",
        "doc_site_publication_builds",
        ["content_hash"],
    )

    # Now that both tables exist, close the loop. `render_as_batch` is on, so SQLite
    # gets this by rebuilding the table, which is the only way it accepts a new
    # foreign key at all.
    with op.batch_alter_table("doc_site_publications") as batch:
        batch.create_foreign_key(
            "fk_publication_current_build",
            "doc_site_publication_builds",
            ["current_build_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    # The foreign key goes first, or SQLite's table rebuild finds a table that is
    # about to disappear.
    with op.batch_alter_table("doc_site_publications") as batch:
        batch.drop_constraint("fk_publication_current_build", type_="foreignkey")
    op.drop_table("doc_site_publication_builds")
    op.drop_table("doc_site_publications")
