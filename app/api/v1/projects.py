import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, Query, Request, UploadFile, File, HTTPException
from app.dependencies import DbSession, CurrentUser, ManagerUser
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate, ProjectSourceCreate, ProjectSourceOut
from app.services.project_service import ProjectService
from app.services.audit_service import AuditService
from app.config import get_settings

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


_ALLOWED_EXTENSIONS = {
    # archives (treated as repo zips)
    ".zip",
    # code
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".kt", ".swift",
    ".c", ".cpp", ".h", ".cs", ".rb", ".php", ".scala", ".sh", ".bash",
    # config / markup
    ".toml", ".yaml", ".yml", ".json", ".xml", ".env", ".ini", ".cfg",
    # docs / text
    ".md", ".mdx", ".txt", ".rst", ".pdf",
    # web
    ".html", ".css",
}


@router.post("/{project_id}/upload", response_model=ProjectSourceOut, status_code=201)
async def upload_source(
    project_id: int,
    db: DbSession,
    user: ManagerUser,
    file: UploadFile = File(...),
):
    """
    Upload a file or zip archive as a project source.
    - ZIP files are extracted to a per-project scratch directory.
    - Single files are saved and referenced directly.
    The resulting path is registered as a 'local' source on the project.
    """
    settings = get_settings()
    suffix = Path(file.filename or "upload").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{suffix}' is not allowed. Supported: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )

    upload_root = Path(settings.REPO_SCRATCH_DIR) / "uploads" / str(project_id)
    upload_root.mkdir(parents=True, exist_ok=True)

    save_path = upload_root / (file.filename or "upload")
    # Avoid path traversal
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
