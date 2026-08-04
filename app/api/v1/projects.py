import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile

from app.config import get_settings
from app.dependencies import CurrentUser, DbSession, ManagerUser
from app.schemas.job import JobCreate, JobOut
from app.schemas.knowledge import AnalyzeRequest, ComposeRequest, KnowledgeBaseSummary
from app.schemas.project import (
    ProjectCreate,
    ProjectOut,
    ProjectSourceCreate,
    ProjectSourceOut,
    ProjectUpdate,
)
from app.services.audit_service import AuditService
from app.services.job_service import JobService
from app.services.knowledge_service import KnowledgeService
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(req: ProjectCreate, db: DbSession, user: ManagerUser, request: Request):
    project = await ProjectService(db).create(req, user)
    await AuditService(db).log(
        "project.create", "project",
        user_id=user.id, resource_id=project.id,
        details={"name": project.name},
        ip_address=request.client.host if request.client else None,
    )
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    return await ProjectService(db).list(user, limit=limit, offset=offset)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int, db: DbSession, user: CurrentUser):
    return await ProjectService(db).get(project_id, user)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: int, req: ProjectUpdate, db: DbSession, user: ManagerUser):
    return await ProjectService(db).update(project_id, req, user)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: int, db: DbSession, user: ManagerUser, request: Request):
    await ProjectService(db).delete(project_id, user)
    await AuditService(db).log(
        "project.delete", "project",
        user_id=user.id, resource_id=project_id,
        ip_address=request.client.host if request.client else None,
    )


# ── Two-phase routes: analyse first, then choose what to write ────────────────

@router.post("/{project_id}/analyze", response_model=JobOut, status_code=202)
async def analyze_project(
    project_id: int,
    db: DbSession,
    user: ManagerUser,
    request: Request,
    req: AnalyzeRequest = AnalyzeRequest(),
):
    """
    Phase 1 — build the knowledge base. Deliberately takes no document type: the user
    chooses what to write once we know what the codebase contains.
    """
    job = await KnowledgeService(db).start_analysis(project_id, user, force=req.force)
    await AuditService(db).log(
        "project.analyze", "job",
        user_id=user.id, resource_id=job.id,
        details={"project_id": project_id, "force": req.force},
        ip_address=request.client.host if request.client else None,
    )
    return job


@router.get("/{project_id}/knowledge-base", response_model=KnowledgeBaseSummary | None)
async def get_knowledge_base(project_id: int, db: DbSession, user: CurrentUser):
    """
    What we know about this project, plus which document types are worth offering.

    Returns null when the project has never been analysed — the UI shows the analyse
    action instead of a document-type picker.
    """
    return await KnowledgeService(db).get_summary(project_id, user)


@router.post("/{project_id}/compose", response_model=JobOut, status_code=202)
async def compose_documents(
    project_id: int, req: ComposeRequest, db: DbSession, user: ManagerUser, request: Request
):
    """Phase 2 — write the requested documents from the existing knowledge base."""
    job = await KnowledgeService(db).start_composition(project_id, req, user)
    await AuditService(db).log(
        "project.compose", "job",
        user_id=user.id, resource_id=job.id,
        details={"project_id": project_id, "doc_types": req.doc_types},
        ip_address=request.client.host if request.client else None,
    )
    return job


# ── Job routes (project-scoped) ───────────────────────────────────────────────

@router.post("/{project_id}/jobs", response_model=JobOut, status_code=201)
async def create_job(project_id: int, req: JobCreate, db: DbSession, user: ManagerUser, request: Request):
    """
    Legacy single-shot endpoint: analyse and write in one job.

    Kept working for existing clients. New callers should use `/analyze` then
    `/compose`, which avoids re-analysing for every document type.
    """
    from app.workers.tasks.generation_tasks import run_documentation_workflow

    svc = JobService(db)
    job = await svc.create(project_id, req, user)
    task = run_documentation_workflow.delay(job.id)
    await svc.start(job.id, task.id)

    await AuditService(db).log(
        "job.create", "job",
        user_id=user.id, resource_id=job.id,
        details={"project_id": project_id, "config": req.config.model_dump()},
        ip_address=request.client.host if request.client else None,
    )
    return await svc.get(job.id)


@router.get("/{project_id}/jobs", response_model=list[JobOut])
async def list_project_jobs(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    return await JobService(db).list_by_project(project_id, limit=limit, offset=offset)


# ── Source routes ─────────────────────────────────────────────────────────────

@router.post("/{project_id}/sources", response_model=ProjectSourceOut, status_code=201)
async def add_source(project_id: int, req: ProjectSourceCreate, db: DbSession, user: ManagerUser):
    return await ProjectService(db).add_source(
        project_id,
        source_type=req.source_type,
        url_or_path=req.url_or_path,
        user=user,
        branch=req.branch,
        config_json=req.config_json,
    )


@router.delete("/{project_id}/sources/{source_id}", status_code=204)
async def delete_source(project_id: int, source_id: int, db: DbSession, user: ManagerUser):
    await ProjectService(db).delete_source(project_id, source_id, user)


_ALLOWED_EXTENSIONS = {
    ".zip",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".kt", ".swift",
    ".c", ".cpp", ".h", ".cs", ".rb", ".php", ".scala", ".sh", ".bash",
    ".toml", ".yaml", ".yml", ".json", ".xml", ".env", ".ini", ".cfg",
    ".md", ".mdx", ".txt", ".rst", ".pdf",
    ".html", ".css",
}


@router.post("/{project_id}/upload", response_model=ProjectSourceOut, status_code=201)
async def upload_source(
    project_id: int,
    db: DbSession,
    user: ManagerUser,
    file: UploadFile = File(...),
):
    settings = get_settings()
    suffix = Path(file.filename or "upload").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{suffix}' is not allowed. Supported: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )

    upload_root = Path(settings.REPO_SCRATCH_DIR) / "uploads" / str(project_id)
    upload_root.mkdir(parents=True, exist_ok=True)

    save_path = upload_root / Path(file.filename or "upload").name

    with save_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    if suffix == ".zip":
        extract_dir = upload_root / save_path.stem
        extract_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(save_path, "r") as zf:
            zf.extractall(extract_dir)
        source_path = str(extract_dir)
    else:
        source_path = str(save_path)

    source = await ProjectService(db).add_source(
        project_id,
        source_type="local",
        url_or_path=source_path,
        user=user,
        branch=None,
        config_json={"original_filename": file.filename},
    )
    return source
