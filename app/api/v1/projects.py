import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile

from app.config import get_settings
from app.dependencies import CurrentUser, DbSession, ManagerUser
from app.schemas.job import JobCreate, JobOut
from app.features import FEATURES, state_for
from app.schemas.knowledge import (
    FeatureOut,
    AddPageRequest,
    AnalyzeRequest,
    ComposeRequest,
    KnowledgeBaseSummary,
    ReviseRequest,
)
from app.schemas.project import (
    ProjectCreate,
    ProjectCreateWithSource,
    ProjectOut,
    ProjectSourceCreate,
    ProjectSourceOut,
    ProjectUpdate,
    SourceProbeOut,
    SourceProbeRequest,
)
from app.schemas.site import (
    EXPORT_FORMATS,
    CreateVersionRequest,
    SiteOut,
    SitePageDetail,
    SiteVersionOut,
)
from app.services.audit_service import AuditService
from app.services.job_service import JobService
from app.features.documentation.services.documentation_service import DocumentationService
from app.services.knowledge_service import KnowledgeService
from app.features.documentation.services.page_builder_service import PageBuilderService
from app.features.documentation.services.revision_service import RevisionService
from app.services.project_service import ProjectService
from app.features.documentation.services.site_service import SiteService
from app.services.source_service import SourceService

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


# ── Source validation ─────────────────────────────────────────────────────────

@router.post("/sources:probe", response_model=SourceProbeOut)
async def probe_source(req: SourceProbeRequest, user: ManagerUser):
    """
    Fetch a source and report what is in it — without creating anything.

    Lets the UI say "Fetching repository… found 142 files" and surface a real error
    before a project exists.
    """
    probe = await SourceService().probe(req.source_type, req.url_or_path, req.branch)
    return SourceProbeOut(**probe.to_dict())


@router.post("/with-source", response_model=ProjectOut, status_code=201)
async def create_project_with_source(
    req: ProjectCreateWithSource, db: DbSession, user: ManagerUser, request: Request
):
    """
    Create a project and attach its first source atomically.

    The source is validated first; a failure returns 422 and leaves nothing behind.
    Previously the project was created before the source was checked, so a typo'd URL
    left an empty project the user had to clean up.
    """
    probe = await SourceService().probe(req.source_type, req.url_or_path, req.branch)
    if not probe.ok:
        raise HTTPException(status_code=422, detail=probe.error or "Source is not usable")

    svc = ProjectService(db)
    project = await svc.create(
        ProjectCreate(name=req.name, description=req.description), user
    )
    await svc.add_source(
        project.id,
        source_type=req.source_type,
        url_or_path=req.url_or_path,
        user=user,
        branch=req.branch,
        config_json={
            **(req.config_json or {}),
            "probe": {
                "file_count": probe.file_count,
                "analysable_files": probe.analysable_files,
                "languages": probe.languages,
                "commit_sha": probe.commit_sha,
            },
        },
    )
    await AuditService(db).log(
        "project.create", "project",
        user_id=user.id, resource_id=project.id,
        details={"name": project.name, "source_type": req.source_type},
        ip_address=request.client.host if request.client else None,
    )
    return await svc.get(project.id, user)


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


@router.get("/{project_id}/features", response_model=list[FeatureOut])
async def get_features(project_id: int, db: DbSession, user: CurrentUser):
    """
    What this codebase currently unlocks, and what it does not.

    Every feature is returned, including the ones this project cannot run yet, because
    the locked ones are how a reader learns the shape of the product without being
    sold it. The reason says what to do rather than what went wrong — a project that
    has never been analysed is not an error, it is a first step nobody has taken.
    """
    await ProjectService(db).get(project_id, user)
    kb = await KnowledgeService(db).latest_status(project_id)

    return [
        FeatureOut(
            id=f.id,
            label=f.label,
            blurb=f.blurb,
            needs=list(f.needs),
            route=f.route.format(id=project_id),
            state=state,
            reason=reason,
        )
        for f in FEATURES
        for state, reason in [state_for(f, kb)]
    ]


@router.get("/{project_id}/site", response_model=SiteOut | None)
async def get_site(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    version: str | None = Query(None, description="A version label. Omit for the live site."),
):
    """
    The project's documentation site: the whole map, with per-page status.

    Planned pages are returned alongside written ones — the nav doubles as the
    roadmap for this project's documentation, so the UI can grey out what does not
    exist yet and offer to generate it. Returns null before the first analysis.
    """
    return await SiteService(db).get_site(project_id, user, version)


@router.get("/{project_id}/site/versions", response_model=list[SiteVersionOut])
async def list_site_versions(project_id: int, db: DbSession, user: CurrentUser):
    """Frozen snapshots of the site, newest first."""
    return await SiteService(db).list_versions(project_id, user)


@router.post("/{project_id}/site/versions", response_model=SiteVersionOut, status_code=201)
async def create_site_version(
    project_id: int, req: CreateVersionRequest, db: DbSession, user: ManagerUser
):
    """
    Freeze the site as it stands, under a label.

    Copies every written page rather than referencing it — the live pages keep
    changing, which is the point of them, and a version that quietly followed them
    would not be a version.
    """
    return await SiteService(db).create_version(project_id, req.label, user, req.notes)


@router.get("/{project_id}/site/export")
async def export_site(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    format: str = Query("markdown", description=f"One of: {', '.join(EXPORT_FORMATS)}"),
    version: str | None = Query(None, description="A version label. Omit for the live site."),
):
    """
    The whole site as a downloadable archive.

    `html` is our own theme as static files — no build step, no network, openable
    with `file://`. `mkdocs` and `docusaurus` are projects a team can build and host.
    `markdown` is the page tree as stored, for anyone who wants neither.

    Built in memory and streamed back rather than stored: an export is a snapshot of
    what you are looking at now, and a stored copy of a thing that regenerates itself
    is stale the moment it is written.
    """
    data, filename, media_type = await SiteService(db).export(
        project_id, format, user, version
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{project_id}/site/pages/{section_slug}/{slug}", response_model=SitePageDetail)
async def get_site_page(
    project_id: int,
    section_slug: str,
    slug: str,
    db: DbSession,
    user: CurrentUser,
    version: str | None = Query(None, description="A version label. Omit for the live site."),
):
    """
    One page of the site, with its prose.

    Separate from `/site` because the map is fetched on every nav render and a
    thirty-page site's markdown is megabytes. A planned page resolves too, with no
    content — the reader shows what it is going to cover instead.
    """
    return await SiteService(db).get_page(project_id, section_slug, slug, user, version)


@router.post("/{project_id}/site/pages", response_model=SitePageDetail, status_code=201)
async def add_site_page(
    project_id: int,
    req: AddPageRequest,
    db: DbSession,
    user: ManagerUser,
    request: Request,
):
    """
    Add a page the analysis never proposed, from a free-text description.

    Creates it as `planned` — with a title, an intent and the anchor files retrieval
    says are relevant — and stops there. Nothing is written. Those anchor files are
    what the whole write depends on, and this is the one moment they can be looked at
    and rejected before a quality-tier call per heading is spent on them.

    The page is `pinned`, so the next analysis cannot orphan it for the crime of not
    being in the model's proposal.
    """
    page = await PageBuilderService(db).propose(
        project_id, req.section_slug, req.request, user, title=req.title
    )
    await AuditService(db).log(
        "site.page.add", "doc_page",
        user_id=user.id, resource_id=page.id,
        details={
            "project_id": project_id,
            "address": f"{page.section_slug}/{page.slug}",
            "request": req.request[:280],
        },
        ip_address=request.client.host if request.client else None,
    )
    return await SiteService(db).get_page(project_id, page.section_slug, page.slug, user)


@router.post(
    "/{project_id}/site/pages/{section_slug}/{slug}/revise",
    response_model=JobOut,
    status_code=202,
)
async def revise_site_page(
    project_id: int,
    section_slug: str,
    slug: str,
    req: ReviseRequest,
    db: DbSession,
    user: ManagerUser,
    request: Request,
):
    """
    Rewrite one heading of a page, or the whole page, against instructions.

    `anchor` is the `anchor_id` of a `##` heading — the id the studio already stamps
    on rendered headings. Omit it to revise the entire page.

    Everything refusable is refused here rather than inside the worker: a page still
    being written, a heading that no longer exists, an anchor matching two headings.
    The result is a message instead of a job that fails two minutes later.
    """
    job = await RevisionService(db).start(
        project_id, section_slug, slug, user,
        instructions=req.instructions,
        anchor=req.anchor,
    )
    await AuditService(db).log(
        "site.page.revise", "job",
        user_id=user.id, resource_id=job.id,
        details={
            "project_id": project_id,
            "address": f"{section_slug}/{slug}",
            "anchor": req.anchor,
        },
        ip_address=request.client.host if request.client else None,
    )
    return job


@router.get("/{project_id}/site/pages/{section_slug}/{slug}/revisions", response_model=list[JobOut])
async def list_page_revisions(
    project_id: int,
    section_slug: str,
    slug: str,
    db: DbSession,
    user: CurrentUser,
    anchor: str | None = Query(None, description="Only turns against this heading."),
):
    """
    The revision turns against this page, oldest first.

    This is the conversation. It is not stored in a table of its own — each turn is a
    job carrying its anchor and its instruction — so a panel reopened after a reload
    shows the same history the model was given.
    """
    return await RevisionService(db).transcript(project_id, section_slug, slug, user, anchor)


@router.delete("/{project_id}/site/pages/{section_slug}/{slug}", status_code=204)
async def delete_site_page(
    project_id: int,
    section_slug: str,
    slug: str,
    db: DbSession,
    user: ManagerUser,
    request: Request,
) -> None:
    """
    Remove a page from the live documentation site.

    Deliberately distinct from what re-analysis does: a page the model stops
    proposing becomes `orphaned`, because its slug is a URL somebody may have
    bookmarked. A person asking for it gone is a different act and gets a real
    delete — audited, because nothing else in this API destroys written prose.

    Frozen versions keep their copy. A page being written is refused.
    """
    await SiteService(db).delete_page(project_id, section_slug, slug, user)
    await AuditService(db).log(
        "site.page.delete", "doc_page",
        user_id=user.id, resource_id=project_id,
        details={"project_id": project_id, "address": f"{section_slug}/{slug}"},
        ip_address=request.client.host if request.client else None,
    )


@router.post("/{project_id}/compose", response_model=JobOut, status_code=202)
async def compose_documents(
    project_id: int, req: ComposeRequest, db: DbSession, user: ManagerUser, request: Request
):
    """
    Phase 2 — write from the existing knowledge base.

    `page_slugs` writes pages into the project's documentation site; without it this
    is the original one-document-per-type path. An unknown page address or a scope
    over `SITE_MAX_PAGES_PER_JOB` comes back 422 before any job is created.
    """
    job = await DocumentationService(db).start(project_id, req, user)
    await AuditService(db).log(
        "project.compose", "job",
        user_id=user.id, resource_id=job.id,
        details={
            "project_id": project_id,
            "doc_types": req.doc_types,
            # The resolved scope, not what was asked for: "api" becomes the pages it
            # actually expanded to, which is what the job will be judged against.
            "page_slugs": (job.config_json or {}).get("page_slugs", []),
        },
        ip_address=request.client.host if request.client else None,
    )
    return job


# ── Job routes (project-scoped) ───────────────────────────────────────────────

@router.post("/{project_id}/jobs", response_model=JobOut, status_code=201)
async def create_job(
    project_id: int, req: JobCreate, db: DbSession, user: ManagerUser, request: Request
):
    """
    Legacy single-shot endpoint: analyse and write in one job.

    Kept working for existing clients. New callers should use `/analyze` then
    `/compose`, which avoids re-analysing for every document type.
    """
    from app.features.documentation.tasks.generation_tasks import run_documentation_workflow

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
            detail=(
                f"File type '{suffix}' is not allowed. "
                f"Supported: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            ),
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
