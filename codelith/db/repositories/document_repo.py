from sqlalchemy import select

from codelith.db.repositories.base import BaseRepository
from codelith.models.document import Document, DocumentExport


class DocumentRepository(BaseRepository[Document]):
    model = Document

    async def list_by_project(self, project_id: int, limit: int = 100, offset: int = 0) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[Document]:
        result = await self.session.execute(
            select(Document).order_by(Document.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_job(self, job_id: int) -> list[Document]:
        result = await self.session.execute(
            select(Document).where(Document.job_id == job_id)
        )
        return list(result.scalars().all())


class DocumentExportRepository(BaseRepository[DocumentExport]):
    model = DocumentExport
