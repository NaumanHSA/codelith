"""
The code graph as rows.

Neo4j stores this as nodes and edges, which is the natural shape for it and the
reason the service is there at all. But only three questions are ever asked of it —
who imports this, who calls this, what might break — and two of the three are a
single join. The third is a transitive walk, which every SQL database has done with a
recursive CTE for a decade.

So solo mode keeps the same graph in six tables. Not because SQL is better at graphs,
but because a person reading one repository on one machine should not have to run a
graph database to ask what calls a function.

Scoped by `(project_id, kb_id)` exactly as the Neo4j subgraph is: a knowledge base is
pinned to a commit, and two analyses of the same repository at different commits must
not merge. Nothing here is language-specific — imports arrive already resolved, which
is `LanguageProvider`'s job.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from codelith.db.base import Base


class _Scoped(Base):
    """Every graph table carries the same scope and drops with its knowledge base."""

    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kb_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class GraphFile(_Scoped):
    __tablename__ = "graph_files"

    path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    module_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    loc: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("ix_graph_files_scope_path", "project_id", "kb_id", "path"),)


class GraphModule(_Scoped):
    __tablename__ = "graph_modules"

    key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)


class GraphSymbol(_Scoped):
    __tablename__ = "graph_symbols"

    path: Mapped[str] = mapped_column(Text, nullable=False)
    qname: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visibility: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (
        Index("ix_graph_symbols_scope_qname", "project_id", "kb_id", "qname"),
        Index("ix_graph_symbols_scope_path", "project_id", "kb_id", "path"),
    )


class GraphImport(_Scoped):
    """One file importing another. Both ends are repository paths."""

    __tablename__ = "graph_imports"

    src: Mapped[str] = mapped_column(Text, nullable=False)
    dst: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        # The blast-radius walk joins `dst` to `src` repeatedly, so both directions
        # are indexed — a recursive CTE over an unindexed edge table is a table scan
        # per level.
        Index("ix_graph_imports_scope_dst", "project_id", "kb_id", "dst"),
        Index("ix_graph_imports_scope_src", "project_id", "kb_id", "src"),
    )


class GraphPackage(_Scoped):
    """A file and the external package it depends on."""

    __tablename__ = "graph_packages"

    src: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class GraphCall(_Scoped):
    __tablename__ = "graph_calls"

    src_path: Mapped[str] = mapped_column(Text, nullable=False)
    src_qname: Mapped[str] = mapped_column(Text, nullable=False)
    dst_path: Mapped[str] = mapped_column(Text, nullable=False)
    dst_qname: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("ix_graph_calls_scope_dst", "project_id", "kb_id", "dst_qname"),
    )
