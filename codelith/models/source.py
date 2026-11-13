"""
The files of each reading, kept the way git keeps them.

Analysis used to discard the checkout and keep only search chunks, which overlap in
places and leave gaps in others, so no reading could show a whole file and no two
readings could be compared line by line. Now every reading keeps its files.

**Each distinct content is stored once.** `source_blobs` is keyed by the SHA-256 of
the text and holds it compressed; `reading_files` says which content each path had
in one reading. A reading in which five files changed adds five blobs, and every
reading of every codebase on the machine shares the rest. Nothing here is ever
rewritten: a blob is immutable, and a reading's file list is written once.

Blobs are shared, so deleting a reading or a codebase removes its file list, and
`SourceRepository.sweep` removes whatever content no reading uses any more.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from codelith.db.base import Base, TimestampMixin
from codelith.db.types import json_column


class SourceBlob(Base, TimestampMixin):
    __tablename__ = "source_blobs"

    #: SHA-256 of the UTF-8 text, hex.
    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: The text, zlib-compressed.
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: Uncompressed bytes and lines, so listings need not decompress anything.
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ReadingFile(Base):
    __tablename__ = "reading_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    blob_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: The language a provider parsed it as, or what kind of project file it is.
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    #: For a project file (`manifest`, `lockfile`, `env`, `docker`, `ci`, `tooling`,
    #: `docs`); empty for source code.
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: True when the stored text is not what the file held: a real `.env` keeps its
    #: variable names and none of its values.
    masked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("kb_id", "path", name="uq_reading_files_kb_path"),
        Index("ix_reading_files_kb_kind", "kb_id", "kind"),
    )


class SourceCommit(Base):
    """
    One commit of a codebase's history, as git had it when a reading was taken: enough
    to list the commits between two readings and what each touched. Kept per codebase,
    once per commit, whichever reading saw it. The author's name and never an email.
    """

    __tablename__ = "source_commits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sha: Mapped[str] = mapped_column(String(40), nullable=False)
    #: Parent hashes, as git rewrote them for the codebase's folder.
    parents_json: Mapped[list] = mapped_column(json_column(), nullable=False, default=list)
    author: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    authored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Paths it changed, relative to the codebase's folder. Empty for a merge.
    files_json: Mapped[list] = mapped_column(json_column(), nullable=False, default=list)

    __table_args__ = (UniqueConstraint("project_id", "sha", name="uq_source_commits_project_sha"),)


__all__ = ["ReadingFile", "SourceBlob", "SourceCommit"]
