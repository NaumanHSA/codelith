from fastapi import APIRouter, Query
from codelith.dependencies import DbSession, CurrentUser
from codelith.schemas.document import DocumentOut, DocumentUpdate, ExportUrlOut
from codelith.apps.documentation.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    db: DbSession,
    user: CurrentUser,
    project_id: int | None = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
):
    svc = DocumentService(db)
    if project_id is not None:
        return await svc.list_by_project(project_id, limit=limit, offset=offset)
    return await svc.list_all(limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(document_id: int, db: DbSession, user: CurrentUser):
    return await DocumentService(db).get(document_id)


@router.patch("/{document_id}", response_model=DocumentOut)
async def update_document(document_id: int, req: DocumentUpdate, db: DbSession, user: CurrentUser):
    return await DocumentService(db).update(document_id, title=req.title, content_markdown=req.content_markdown)


@router.post("/{document_id}/publish", response_model=DocumentOut)
async def publish_document(document_id: int, db: DbSession, user: CurrentUser):
    return await DocumentService(db).publish(document_id)


@router.get("/{document_id}/export", response_model=ExportUrlOut, status_code=202)
async def export_document(
    document_id: int,
    db: DbSession,
    user: CurrentUser,
    format: str = Query(..., description="pdf | docx | html | mkdocs | docusaurus"),
):
    from codelith.apps.documentation.tasks.export_tasks import export_document_task

    export_document_task.delay(document_id, format)
    # Return a polling URL — the worker will upload and record the real path when done
    return {"url": f"/api/v1/documents/{document_id}/export/status?format={format}"}
