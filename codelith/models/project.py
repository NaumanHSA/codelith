from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from codelith.db.base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="projects")  # type: ignore[name-defined]
    sources: Mapped[list["ProjectSource"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="project", cascade="all, delete-orphan")  # type: ignore[name-defined]
    documents: Mapped[list["Document"]] = relationship(back_populates="project", cascade="all, delete-orphan")  # type: ignore[name-defined]
    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(back_populates="project", cascade="all, delete-orphan")  # type: ignore[name-defined]
    # One documentation site per project, grown a section at a time.
    doc_site: Mapped["DocSite | None"] = relationship(back_populates="project", cascade="all, delete-orphan", uselist=False)  # type: ignore[name-defined]


class ProjectSource(Base, TimestampMixin):
    __tablename__ = "project_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)  # github | gitlab | local | pdf | openapi
    url_or_path: Mapped[str] = mapped_column(Text, nullable=False)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    project: Mapped["Project"] = relationship(back_populates="sources")
