import asyncio
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from codelith.dependencies import CurrentUser, CurrentUserOrToken, DbSession, ManagerUser
from codelith.schemas.job import AgentLogOut, JobOut
from codelith.services.audit_service import AuditService
from codelith.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("", response_model=list[JobOut])
async def list_jobs(
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, description="Filter to one status."),
):
    """Every job across the organisation's projects, newest first."""
    return await JobService(db).list_all(user, limit=limit, offset=offset, status=status)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: int, db: DbSession, user: CurrentUser):
    return await JobService(db).get(job_id)


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: int, db: DbSession, user: ManagerUser, request: Request):
    """
    Remove a job from the record.

    A live job is cancelled first — deleting the row does not stop the worker, and a
    job whose row has gone but whose task is still writing is the worst of both.
    Documents and pages it produced survive: they carry their own copy of what
    produced them, and losing written work to a tidied job list would be indefensible.
    """
    await JobService(db).delete(job_id)
    await AuditService(db).log(
        "job.delete", "job",
        user_id=user.id, resource_id=job_id,
        ip_address=request.client.host if request.client else None,
    )


@router.get("/{job_id}/logs", response_model=list[AgentLogOut])
async def get_job_logs(job_id: int, db: DbSession, user: CurrentUser):
    return await JobService(db).get_logs(job_id)


# Approving a held composition lives at
# `POST /projects/{project_id}/compose/{job_id}/approve`, not here. It has to dispatch
# the documentation feature's task to publish what was written, and this module is not
# a composition root — it may not name a feature. The route that used to sit here only
# set the status to `running`, which left approved jobs running forever with no worker
# on them.


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
async def stream_job_logs(job_id: int, db: DbSession, user: CurrentUserOrToken):
    """
    Server-Sent Events stream. Accepts JWT via Authorization header or ?token= query param
    (needed because EventSource cannot set custom headers).
    """
    from codelith.db.repositories.job_repo import AgentLogRepository, JobRepository
    from codelith.db.session import AsyncSessionLocal

    async def event_generator():
        last_id = 0
        for _ in range(600):  # 10 min max
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
                        "timestamp": log.created_at.isoformat(),
                        "extra": log.extra_json,
                    })
                    yield f"data: {payload}\n\n"
                    last_id = log.id

                if job.status in _TERMINAL_STATUSES:
                    yield f"event: done\ndata: {{\"status\": \"{job.status}\"}}\n\n"
                    return

            await asyncio.sleep(1.0)

        yield "event: timeout\ndata: {}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
