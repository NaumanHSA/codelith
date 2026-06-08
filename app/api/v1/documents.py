from fastapi import APIRouter, Query
from app.dependencies import DbSession, CurrentUser
from app.schemas.document import DocumentOut, ExportRequest, DocumentExportOut
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
):
    return await DocumentService(db).list_by_project(project_id, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(document_id: int, db: DbSession, user: CurrentUser):
    return await DocumentService(db).get(document_id)


@router.post("/{document_id}/publish", response_model=DocumentOut)
async def publish_document(document_id: int, db: DbSession, user: CurrentUser):
    return await DocumentService(db).publish(document_id)


@router.post("/{document_id}/export", response_model=DocumentExportOut, status_code=202)
async def export_document(document_id: int, req: ExportRequest, db: DbSession, user: CurrentUser):
    from app.workers.tasks.export_tasks import export_document_task

    export_document_task.delay(document_id, req.format)
    # Return placeholder — Celery will record the real export on completion
    svc = DocumentService(db)
    doc = await svc.get(document_id)
    return await svc.record_export(document_id, req.format, f"pending/{document_id}/{req.format}")
