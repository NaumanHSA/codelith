from datetime import datetime

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: int
    project_id: int
    job_id: int | None
    doc_type: str
    title: str
    content_markdown: str | None
    storage_path: str | None
    version: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentExportOut(BaseModel):
    id: int
    document_id: int
    format: str
    storage_path: str
    file_size_bytes: int | None

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    title: str | None = None
    content_markdown: str | None = None


class ExportRequest(BaseModel):
    format: str  # pdf | docx | html | mkdocs | docusaurus


class ExportUrlOut(BaseModel):
    url: str
