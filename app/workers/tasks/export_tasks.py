import asyncio
import structlog
from app.workers.celery_app import celery_app
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)


@celery_app.task(name="export.export_document", bind=True, max_retries=2)
def export_document_task(self, document_id: int, format: str) -> dict:
    return asyncio.get_event_loop().run_until_complete(_export(document_id, format))


async def _export(document_id: int, format: str) -> dict:
    async with AsyncSessionLocal() as db:
        try:
            from app.db.repositories.document_repo import DocumentRepository, DocumentExportRepository
            from app.formatters.markdown import MarkdownFormatter
            from app.storage.s3 import StorageClient

            doc = await DocumentRepository(db).get_by_id(document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            if format == "markdown":
                formatter = MarkdownFormatter()
                content_bytes = formatter.format(doc)
                storage_key = f"exports/{doc.project_id}/{document_id}/document.md"
            else:
                raise NotImplementedError(f"Format '{format}' not yet implemented (Phase 4)")

            storage = StorageClient()
            await storage.upload_bytes(content_bytes, storage_key)

            export = await DocumentExportRepository(db).create(
                document_id=document_id,
                format=format,
                storage_path=storage_key,
                file_size_bytes=len(content_bytes),
            )
            await db.commit()
            return {"export_id": export.id, "storage_path": storage_key}

        except Exception as exc:
            logger.error("export_failed", document_id=document_id, format=format, error=str(exc))
            raise
