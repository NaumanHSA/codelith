import asyncio
import structlog
from app.workers.celery_app import celery_app
from app.db.session import AsyncSessionLocal
from app.services.job_service import JobService

logger = structlog.get_logger(__name__)


@celery_app.task(name="generation.run_documentation_workflow", bind=True, max_retries=1)
def run_documentation_workflow(self, job_id: int) -> dict:
    return asyncio.get_event_loop().run_until_complete(_run_workflow(job_id))


async def _run_workflow(job_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        job_svc = JobService(db)
        try:
            from app.workflows.documentation_workflow import DocumentationWorkflow
            from app.db.repositories.job_repo import JobRepository
            from app.db.repositories.project_repo import ProjectRepository

            job = await JobRepository(db).get_with_steps(job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")

            project = await ProjectRepository(db).get_by_id_with_sources(job.project_id)
            if not project:
                raise ValueError(f"Project {job.project_id} not found")

            await job_svc.write_log(job_id, "coordinator", "info", "Documentation workflow started")

            workflow = DocumentationWorkflow(project=project, job=job, db=db)
            result = await workflow.run()

            if result.get("requires_review"):
                await job_svc.request_review(job_id)
            else:
                await job_svc.complete(job_id)

            await job_svc.write_log(job_id, "coordinator", "info", "Documentation workflow finished")
            return result

        except Exception as exc:
            logger.error("workflow_failed", job_id=job_id, error=str(exc))
            await job_svc.fail(job_id, str(exc))
            raise
