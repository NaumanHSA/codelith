from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from codelith.config import get_settings
from codelith.db.base import Base, TimestampMixin


class CodeChunk(Base, TimestampMixin):
    """A chunk of source code or document text with its embedding vector stored via pgvector."""

    __tablename__ = "code_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Knowledge base this chunk belongs to. Scoping chunks to a KB generation lets a
    #: re-analysis replace them atomically instead of accumulating across runs.
    kb_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Where this chunk came from
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunk_type: Mapped[str] = mapped_column(String(50), nullable=False)  # code | docstring | markdown | comment

    # The raw text content of this chunk
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Character offsets within the source file
    start_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The embedding vector — dimension set from config
    embedding: Mapped[list[float]] = mapped_column(
        Vector(get_settings().VECTOR_DIMENSIONS), nullable=True
    )
