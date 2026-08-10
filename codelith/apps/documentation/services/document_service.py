from sqlalchemy.ext.asyncio import AsyncSession
from codelith.core.exceptions import NotFoundError
from codelith.db.repositories.document_repo import DocumentRepository, DocumentExportRepository
from codelith.models.document import Document, DocumentExport


class DocumentService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = DocumentRepository(db)
        self.export_repo = DocumentExportRepository(db)
        self.db = db

    async def create(
        self,
        project_id: int,
        job_id: int | None,
        doc_type: str,
        title: str,
        content_markdown: str | None = None,
        storage_path: str | None = None,
    ) -> Document:
        doc = await self.repo.create(
            project_id=project_id,
            job_id=job_id,
            doc_type=doc_type,
            title=title,
            content_markdown=content_markdown,
            storage_path=storage_path,
        )
        await self.db.commit()
        return doc

    async def get(self, document_id: int) -> Document:
        doc = await self.repo.get_by_id(document_id)
        if not doc:
            raise NotFoundError("Document", document_id)
        return doc

    async def list_by_project(self, project_id: int, limit: int = 100, offset: int = 0) -> list[Document]:
        return await self.repo.list_by_project(project_id, limit=limit, offset=offset)

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[Document]:
        return await self.repo.list_all(limit=limit, offset=offset)

    async def update(self, document_id: int, title: str | None = None, content_markdown: str | None = None) -> Document:
        updates = {k: v for k, v in {"title": title, "content_markdown": content_markdown}.items() if v is not None}
        doc = await self.repo.update(document_id, **updates)
        await self.db.commit()
        if not doc:
            raise NotFoundError("Document", document_id)
        return doc

    async def list_by_job(self, job_id: int) -> list[Document]:
        return await self.repo.list_by_job(job_id)

    async def publish(self, document_id: int) -> Document:
        doc = await self.repo.update(document_id, status="published")
        await self.db.commit()
        return doc  # type: ignore[return-value]

    async def record_export(
        self, document_id: int, format: str, storage_path: str, file_size_bytes: int | None = None
    ) -> DocumentExport:
        export = await self.export_repo.create(
            document_id=document_id,
            format=format,
            storage_path=storage_path,
            file_size_bytes=file_size_bytes,
        )
        await self.db.commit()
        return export
