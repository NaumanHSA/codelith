"""code_graph_tables

The code graph as rows, so it can be asked without a graph database.

Neo4j remains the backing in server mode and these tables stay empty there. Solo mode
writes them instead: one machine reading one repository should not have to run a graph
database to ask what calls a function.

Six tables mirroring the graph's own shape — files, modules, symbols, imports,
packages, calls — each scoped by `(project_id, kb_id)` exactly as the Neo4j subgraph
is, because a knowledge base is pinned to a commit and two analyses of the same
repository must not merge.

The indexes are not decoration. `get_blast_radius` is a recursive CTE that joins
`dst` to `src` once per level; without both directions indexed each level is a table
scan.

Revision ID: c81f4a2e9b70
Revises: f2b9c41d77ae
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c81f4a2e9b70"
down_revision: str | None = "f2b9c41d77ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _scope(*extra: sa.Column) -> list:
    return [
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kb_id", sa.Integer, nullable=True),
        *extra,
    ]


def upgrade() -> None:
    op.create_table(
        "graph_files",
        *_scope(
            sa.Column("path", sa.Text, nullable=False),
            sa.Column("language", sa.String(50), nullable=True),
            sa.Column("module_key", sa.Text, nullable=True),
            sa.Column("loc", sa.Integer, nullable=True),
        ),
    )
    op.create_table(
        "graph_modules",
        *_scope(
            sa.Column("key", sa.Text, nullable=False),
            sa.Column("name", sa.Text, nullable=True),
            sa.Column("role", sa.String(50), nullable=True),
        ),
    )
    op.create_table(
        "graph_symbols",
        *_scope(
            sa.Column("path", sa.Text, nullable=False),
            sa.Column("qname", sa.Text, nullable=False),
            sa.Column("name", sa.Text, nullable=True),
            sa.Column("kind", sa.String(50), nullable=True),
            sa.Column("line", sa.Integer, nullable=True),
            sa.Column("end_line", sa.Integer, nullable=True),
            sa.Column("visibility", sa.String(20), nullable=True),
        ),
    )
    op.create_table(
        "graph_imports",
        *_scope(
            sa.Column("src", sa.Text, nullable=False),
            sa.Column("dst", sa.Text, nullable=False),
        ),
    )
    op.create_table(
        "graph_packages",
        *_scope(
            sa.Column("src", sa.Text, nullable=False),
            sa.Column("name", sa.Text, nullable=False),
        ),
    )
    op.create_table(
        "graph_calls",
        *_scope(
            sa.Column("src_path", sa.Text, nullable=False),
            sa.Column("src_qname", sa.Text, nullable=False),
            sa.Column("dst_path", sa.Text, nullable=False),
            sa.Column("dst_qname", sa.Text, nullable=False),
        ),
    )

    for table in (
        "graph_files", "graph_modules", "graph_symbols",
        "graph_imports", "graph_packages", "graph_calls",
    ):
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])
        op.create_index(f"ix_{table}_kb_id", table, ["kb_id"])

    op.create_index("ix_graph_files_scope_path", "graph_files", ["project_id", "kb_id", "path"])
    op.create_index("ix_graph_symbols_scope_qname", "graph_symbols", ["project_id", "kb_id", "qname"])
    op.create_index("ix_graph_symbols_scope_path", "graph_symbols", ["project_id", "kb_id", "path"])
    # Both directions: the blast-radius CTE walks edges backwards, once per level.
    op.create_index("ix_graph_imports_scope_dst", "graph_imports", ["project_id", "kb_id", "dst"])
    op.create_index("ix_graph_imports_scope_src", "graph_imports", ["project_id", "kb_id", "src"])
    op.create_index("ix_graph_calls_scope_dst", "graph_calls", ["project_id", "kb_id", "dst_qname"])


def downgrade() -> None:
    for table in (
        "graph_calls", "graph_packages", "graph_imports",
        "graph_symbols", "graph_modules", "graph_files",
    ):
        op.drop_table(table)
