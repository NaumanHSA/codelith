from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.db.repositories.base import BaseRepository
from app.models.job import Job, JobStep, AgentLog


class JobRepository(BaseRepository[Job]):
    model = Job

    async def get_with_steps(self, id: int) -> Job | None:
        result = await self.session.execute(
            select(Job)
            .options(selectinload(Job.steps), selectinload(Job.project))
            .where(Job.id == id)
        )
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: int, limit: int = 50, offset: int = 0) -> list[Job]:
        result = await self.session.execute(
            select(Job)
            .options(selectinload(Job.steps), selectinload(Job.project))
            .where(Job.project_id == project_id)
            .order_by(Job.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_for_org(
        self,
        org_id: int,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[Job]:
        """
        Every job across the organisation's projects, newest first.

        Joined to `projects` rather than filtered by a denormalised org column: a job
        belongs to a project, and duplicating the ownership would be one more thing
        to keep in step.
        """
        from app.models.project import Project

        stmt = (
            select(Job)
            .options(selectinload(Job.steps), selectinload(Job.project))
            .join(Project, Project.id == Job.project_id)
            .where(Project.org_id == org_id)
        )
        if status:
            stmt = stmt.where(Job.status == status)
        stmt = stmt.order_by(Job.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class JobStepRepository(BaseRepository[JobStep]):
    model = JobStep


class AgentLogRepository(BaseRepository[AgentLog]):
    model = AgentLog

    async def list_by_job(self, job_id: int, limit: int = 200) -> list[AgentLog]:
        result = await self.session.execute(
            select(AgentLog)
            .where(AgentLog.job_id == job_id)
            .order_by(AgentLog.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_since(self, job_id: int, after_id: int, limit: int = 50) -> list[AgentLog]:
        result = await self.session.execute(
            select(AgentLog)
            .where(AgentLog.job_id == job_id, AgentLog.id > after_id)
            .order_by(AgentLog.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())
