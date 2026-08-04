from datetime import UTC, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import NotFoundError
from app.db.repositories.job_repo import JobRepository, AgentLogRepository
from app.models.job import Job
from app.models.user import User
from app.schemas.job import JobCreate


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
        )
        await self.db.commit()
        return job  # type: ignore[return-value]

    async def fail(self, job_id: int, error: str) -> Job:
        job = await self.repo.update(
            job_id,
            status="failed",
            error_message=error,
            completed_at=datetime.now(UTC),
        )
        await self.db.commit()
        return job  # type: ignore[return-value]

    async def request_review(self, job_id: int) -> Job:
        job = await self.repo.update(job_id, status="awaiting_review")
        await self.db.commit()
        return job  # type: ignore[return-value]

    async def approve(self, job_id: int, approved: bool, comment: str | None = None) -> Job:
        new_status = "running" if approved else "failed"
        error = None if approved else (comment or "Rejected by reviewer")
        await self.repo.update(job_id, status=new_status, error_message=error)
        await self.db.commit()
        # Re-fetch with steps eager-loaded: this is returned as JobOut, which declares
        # `steps`, and a lazy load during serialization raises MissingGreenlet.
        return await self.get(job_id)

    async def cancel(self, job_id: int) -> Job:
        await self.repo.update(job_id, status="cancelled", completed_at=datetime.now(UTC))
        await self.db.commit()
        return await self.get(job_id)

    async def update_config(self, job_id: int, extra: dict) -> None:
        """Merge extra key/value pairs into the job's config_json."""
        job = await self.repo.get_by_id(job_id)
        if job:
            existing = dict(job.config_json or {})
            existing.update(extra)
            await self.repo.update(job_id, config_json=existing)
            await self.db.commit()

    async def write_log(self, job_id: int, agent_name: str, level: str, message: str, extra: dict | None = None) -> None:
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
