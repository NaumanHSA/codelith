from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)

    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)  # architecture|api|module|tutorial|runbook|...
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)  # S3 key for large docs
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)  # draft|review|published

    project: Mapped["Project"] = relationship(back_populates="documents")  # type: ignore[name-defined]
    job: Mapped["Job"] = relationship(back_populates="documents")  # type: ignore[name-defined]
    exports: Mapped[list["DocumentExport"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentExport(Base, TimestampMixin):
    __tablename__ = "document_exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(50), nullable=False)  # pdf|docx|html|mkdocs|docusaurus
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="exports")
