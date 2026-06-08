import asyncio
import structlog
from app.workers.celery_app import celery_app
from app.db.session import AsyncSessionLocal
from app.services.job_service import JobService

logger = structlog.get_logger(__name__)


@celery_app.task(name="ingestion.run_ingestion_pipeline", bind=True, max_retries=2)
def run_ingestion_pipeline(self, job_id: int) -> dict:
    return asyncio.get_event_loop().run_until_complete(_run_ingestion(job_id))


async def _run_ingestion(job_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        job_svc = JobService(db)
        try:
            from app.ingestion.pipeline import IngestionPipeline
            from app.db.repositories.job_repo import JobRepository
            from app.db.repositories.project_repo import ProjectRepository

            job = await JobRepository(db).get_with_steps(job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")

            project = await ProjectRepository(db).get_by_id_with_sources(job.project_id)
            if not project:
                raise ValueError(f"Project {job.project_id} not found")

            await job_svc.write_log(job_id, "ingestion", "info", "Ingestion pipeline started")

            pipeline = IngestionPipeline(project=project, job_id=job_id, db=db)
            result = await pipeline.run()

            await job_svc.write_log(job_id, "ingestion", "info", "Ingestion pipeline completed", result)
            return result

        except Exception as exc:
            logger.error("ingestion_failed", job_id=job_id, error=str(exc))
            await job_svc.fail(job_id, str(exc))
            raise
