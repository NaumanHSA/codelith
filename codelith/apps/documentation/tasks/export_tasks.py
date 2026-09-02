import structlog

from codelith.db.session import AsyncSessionLocal
from codelith.workers import runner
from codelith.workers.task import task

logger = structlog.get_logger(__name__)


@task("export.export_document")
def export_document_task(document_id: int, format: str) -> dict:
    return runner.run(_export(document_id, format))


async def _export(document_id: int, format: str) -> dict:
    async with AsyncSessionLocal() as db:
        try:
            from codelith.apps.documentation.formatters.markdown import MarkdownFormatter
            from codelith.db.repositories.document_repo import (
                DocumentExportRepository,
                DocumentRepository,
            )
            from codelith.storage import get_storage

            doc = await DocumentRepository(db).get_by_id(document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            if format == "markdown":
                formatter = MarkdownFormatter()
                content_bytes = formatter.format(doc)
                storage_key = f"exports/{doc.project_id}/{document_id}/document.md"
            else:
                raise NotImplementedError(f"Format '{format}' not yet implemented (Phase 4)")

            storage = get_storage()
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
