import structlog

from codelith.db.session import AsyncSessionLocal
from codelith.services.job_service import JobService
from codelith.workers import runner
from codelith.workers.task import task

logger = structlog.get_logger(__name__)


@task("ingestion.run_ingestion_pipeline")
def run_ingestion_pipeline(job_id: int) -> dict:
    return runner.run(_run_ingestion(job_id))


async def _run_ingestion(job_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        job_svc = JobService(db)
        try:
            from codelith.db.repositories.job_repo import JobRepository
            from codelith.db.repositories.project_repo import ProjectRepository
            from codelith.ingestion.pipeline import IngestionPipeline

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
