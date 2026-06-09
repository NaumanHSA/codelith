import asyncio
import json
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from app.dependencies import DbSession, CurrentUser, ManagerUser, ReviewerUser
from app.schemas.job import JobCreate, JobOut, AgentLogOut, JobApproveRequest
from app.services.job_service import JobService
from app.services.audit_service import AuditService

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("/projects/{project_id}/jobs", response_model=JobOut, status_code=201)
async def create_job(project_id: int, req: JobCreate, db: DbSession, user: ManagerUser, request: Request):
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


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: int, db: DbSession, user: CurrentUser):
    return await JobService(db).get(job_id)


@router.get("/{job_id}/logs", response_model=list[AgentLogOut])
async def get_job_logs(job_id: int, db: DbSession, user: CurrentUser):
    return await JobService(db).get_logs(job_id)


@router.post("/{job_id}/approve", response_model=JobOut)
async def approve_job(job_id: int, req: JobApproveRequest, db: DbSession, user: ReviewerUser, request: Request):
    result = await JobService(db).approve(job_id, req.approved, req.comment)
    await AuditService(db).log(
        "job.approve" if req.approved else "job.reject", "job",
        user_id=user.id, resource_id=job_id,
        details={"approved": req.approved, "comment": req.comment},
        ip_address=request.client.host if request.client else None,
    )
    return result


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: int, db: DbSession, user: ManagerUser, request: Request):
    result = await JobService(db).cancel(job_id)
    await AuditService(db).log(
        "job.cancel", "job",
        user_id=user.id, resource_id=job_id,
        ip_address=request.client.host if request.client else None,
    )
    return result


_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@router.get("/{job_id}/stream")
async def stream_job_logs(job_id: int, db: DbSession, user: CurrentUser):
    """
    Server-Sent Events stream of agent log lines for a running job.
    Emits `data: <json>\\n\\n` for each new log entry.
    Closes with `event: done\\ndata: {}\\n\\n` when the job reaches a terminal state.
    """
    from app.db.repositories.job_repo import JobRepository, AgentLogRepository
    from app.db.session import AsyncSessionLocal

    async def event_generator():
        last_id = 0
        poll_interval = 1.0  # seconds between DB polls
        max_idle_iters = 600  # 10 minutes max before giving up

        for _ in range(max_idle_iters):
            async with AsyncSessionLocal() as session:
                job = await JobRepository(session).get_by_id(job_id)
                if job is None:
                    yield "event: error\ndata: {\"detail\": \"Job not found\"}\n\n"
                    return

                new_logs = await AgentLogRepository(session).list_since(job_id, last_id)
                for log in new_logs:
                    payload = json.dumps({
                        "id": log.id,
                        "agent": log.agent_name,
                        "level": log.level,
                        "message": log.message,
                        "extra": log.extra_json,
                    })
                    yield f"data: {payload}\n\n"
                    last_id = log.id

                if job.status in _TERMINAL_STATUSES:
                    yield f"event: done\ndata: {{\"status\": \"{job.status}\"}}\n\n"
                    return

            await asyncio.sleep(poll_interval)

        yield "event: timeout\ndata: {}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
