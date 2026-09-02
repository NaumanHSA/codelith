from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.core.exceptions import NotFoundError
from codelith.db.repositories.job_repo import AgentLogRepository, JobRepository
from codelith.models.job import Job
from codelith.models.user import User
from codelith.schemas.job import JobCreate

logger = structlog.get_logger(__name__)


class JobService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = JobRepository(db)
        self.log_repo = AgentLogRepository(db)
        self.db = db

    async def create(
        self,
        project_id: int,
        req: JobCreate,
        user: User,
        job_type: str = "composition",
        config_overrides: dict | None = None,
        scope: dict | None = None,
    ) -> Job:
        config = req.config.model_dump()
        if config_overrides:
            config.update(config_overrides)
        job = await self.repo.create(
            project_id=project_id,
            created_by=user.id,
            job_type=job_type,
            status="pending",
            config_json=config,
            scope_json=scope or {},
        )
        await self.db.commit()
        return job

    async def get(self, job_id: int) -> Job:
        job = await self.repo.get_with_steps(job_id)
        if not job:
            raise NotFoundError("Job", job_id)
        return job

    async def list_by_project(self, project_id: int, limit: int = 50, offset: int = 0) -> list[Job]:
        return await self.repo.list_by_project(project_id, limit=limit, offset=offset)

    async def start(self, job_id: int, celery_task_id: str) -> Job:
        job = await self.repo.update(
            job_id,
            status="running",
            celery_task_id=celery_task_id,
            started_at=datetime.now(UTC),
        )
        await self.db.commit()
        return job  # type: ignore[return-value]

    async def complete(self, job_id: int) -> Job:
        job = await self.repo.update(
            job_id,
            status="completed",
            completed_at=datetime.now(UTC),
            # A finished job owes nobody a decision; a leftover payload would show up
            # as a pending review forever.
            resume_state_json=None,
        )
        await self.db.commit()
        return job  # type: ignore[return-value]

    async def fail(self, job_id: int, error: str) -> Job:
        job = await self.repo.update(
            job_id,
            status="failed",
            error_message=error,
            completed_at=datetime.now(UTC),
            resume_state_json=None,
        )
        await self.db.commit()
        return job  # type: ignore[return-value]

    async def request_review(self, job_id: int) -> Job:
        job = await self.repo.update(job_id, status="awaiting_review")
        await self.db.commit()
        return job  # type: ignore[return-value]

    async def hold_for_review(self, job_id: int, resume_state: dict) -> Job:
        """
        Park the job and keep what it would need to carry on.

        Status and payload move together on purpose: a job that reads
        `awaiting_review` with nothing stored is one nobody can approve, and the two
        writes are the same decision.
        """
        job = await self.repo.update(
            job_id, status="awaiting_review", resume_state_json=resume_state
        )
        await self.db.commit()
        return job  # type: ignore[return-value]

    async def approve(self, job_id: int, approved: bool, comment: str | None = None) -> Job:
        """
        Record the reviewer's decision. **Does not resume anything.**

        Resuming means dispatching the feature's task, and this service is base code
        that must not import a feature. The caller — a composition root that already
        knows what kind of job this is — dispatches. Calling this alone leaves an
        approved job marked `running` with no worker on it, which was the old bug.
        """
        new_status = "running" if approved else "failed"
        error = None if approved else (comment or "Rejected by reviewer")
        # A rejected job is over: drop the payload so nothing can resume it later.
        extra = {} if approved else {"resume_state_json": None}
        await self.repo.update(job_id, status=new_status, error_message=error, **extra)
        await self.db.commit()
        # Re-fetch with steps eager-loaded: this is returned as JobOut, which declares
        # `steps`, and a lazy load during serialization raises MissingGreenlet.
        return await self.get(job_id)

    async def cancel(self, job_id: int) -> Job:
        """
        Actually stop the job, not just relabel it.

        Cancelling used to be cosmetic: the column changed, the UI said "cancelled",
        and the worker carried on streaming tokens until the document was finished.

        Two things happen here. The flag the running work polls between agents,
        between sections and between streamed chunks is set — that is what actually
        stops it. Then the status is recorded.

        There used to be a third: revoking the task in Celery, so one still queued
        never started. That was always best effort, and with an in-process worker
        there is no queue to revoke from — a job that has not started yet sees the
        flag the moment it does.
        """
        from codelith.core.cancellation import request_cancel

        await self.get(job_id)
        await request_cancel(job_id)

        await self.repo.update(job_id, status="cancelled", completed_at=datetime.now(UTC))
        await self.db.commit()
        return await self.get(job_id)

    async def delete(self, job_id: int) -> None:
        """
        Remove a job from the record.

        Cancels first when it is still live: deleting a row does not stop a worker,
        and a job whose row has gone but whose task is still writing pages is the
        worst of both. Steps and logs cascade; documents and pages do not — they
        keep their own copy of what produced them, and losing a written page because
        someone tidied a job list would be indefensible.
        """
        job = await self.get(job_id)
        if job.status in ("pending", "running"):
            await self.cancel(job_id)
        await self.repo.delete(job_id)
        await self.db.commit()

    async def list_all(
        self, user: User, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> list[Job]:
        """Every job in the user's organisation, newest first."""
        return await self.repo.list_for_org(
            user.org_id or 0, limit=limit, offset=offset, status=status
        )

    async def update_config(self, job_id: int, extra: dict) -> None:
        """Merge extra key/value pairs into the job's config_json."""
        job = await self.repo.get_by_id(job_id)
        if job:
            existing = dict(job.config_json or {})
            existing.update(extra)
            await self.repo.update(job_id, config_json=existing)
            await self.db.commit()

    async def write_log(
        self, job_id: int, agent_name: str, level: str, message: str,
        extra: dict | None = None,
    ) -> None:
        await self.log_repo.create(
            job_id=job_id,
            agent_name=agent_name,
            level=level,
            message=message,
            extra_json=extra or {},
        )
        await self.db.commit()

    async def get_logs(self, job_id: int) -> list:
        return await self.log_repo.list_by_job(job_id)
