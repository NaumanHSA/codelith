from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.models.job import Job

logger = structlog.get_logger(__name__)


class LongTermMemory:
    """
    Project-level memory: check whether a previous job already embedded this
    exact commit so the code_understanding step can be skipped.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def find_cached_job(self, project_id: int, commit_sha: str | None) -> Job | None:
        """
        Return the most recent completed job for this project whose ingestion
        recorded the same git commit SHA. Returns None when no cache hit.
        """
        if not commit_sha:
            return None

        stmt = (
            select(Job)
            .where(Job.project_id == project_id)
            .where(Job.status == "completed")
            .order_by(Job.completed_at.desc())
            .limit(20)
        )
        result = await self.db.execute(stmt)
        jobs: list[Job] = list(result.scalars().all())

        for job in jobs:
            cfg = job.config_json or {}
            if cfg.get("commit_sha") == commit_sha:
                logger.info(
                    "cache_hit",
                    project_id=project_id,
                    commit_sha=commit_sha,
                    cached_job_id=job.id,
                )
                return job

        return None

    async def record_commit_sha(self, job_id: int, commit_sha: str) -> None:
        """Persist the commit SHA into the job's config_json after ingestion."""
        from codelith.db.repositories.job_repo import JobRepository
        repo = JobRepository(self.db)
        job = await repo.get_by_id(job_id)
        if job:
            existing = dict(job.config_json or {})
            existing["commit_sha"] = commit_sha
            await repo.update(job_id, config_json=existing)
            await self.db.commit()
