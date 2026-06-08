from fastapi import APIRouter, Query
from app.dependencies import DbSession, CurrentUser
from app.schemas.job import JobCreate, JobOut, AgentLogOut, JobApproveRequest
from app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("/projects/{project_id}/jobs", response_model=JobOut, status_code=201)
async def create_job(project_id: int, req: JobCreate, db: DbSession, user: CurrentUser):
    from app.workers.tasks.generation_tasks import run_documentation_workflow

    svc = JobService(db)
    job = await svc.create(project_id, req, user)

    # Dispatch to Celery
    task = run_documentation_workflow.delay(job.id)
    await svc.start(job.id, task.id)

    return await svc.get(job.id)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: int, db: DbSession, user: CurrentUser):
    return await JobService(db).get(job_id)


@router.get("/{job_id}/logs", response_model=list[AgentLogOut])
async def get_job_logs(job_id: int, db: DbSession, user: CurrentUser):
    return await JobService(db).get_logs(job_id)


@router.post("/{job_id}/approve", response_model=JobOut)
async def approve_job(job_id: int, req: JobApproveRequest, db: DbSession, user: CurrentUser):
    return await JobService(db).approve(job_id, req.approved, req.comment)


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: int, db: DbSession, user: CurrentUser):
    return await JobService(db).cancel(job_id)
