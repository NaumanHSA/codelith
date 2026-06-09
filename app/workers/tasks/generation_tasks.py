import asyncio
import structlog
from app.workers.celery_app import celery_app
from app.db.session import AsyncSessionLocal
from app.services.job_service import JobService
from app.observability.metrics import job_total, time_job
from app.observability.tracing import workflow_span

logger = structlog.get_logger(__name__)


@celery_app.task(name="generation.run_documentation_workflow", bind=True, max_retries=1)
def run_documentation_workflow(self, job_id: int) -> dict:
    return asyncio.get_event_loop().run_until_complete(_run_workflow(job_id))


async def _run_workflow(job_id: int) -> dict:
    from app.core.sandbox import JobSandbox
    from app.tracing.runtime import create_tracer, set_tracer, reset_tracer, save_trace_artifacts

    sandbox = JobSandbox(job_id)
    sandbox.setup()
    logger.info("sandbox_ready", job_id=job_id, root=str(sandbox.root))

    tracer = create_tracer(
        job_id=str(job_id),
        workflow_type="documentation",
        run_dir=sandbox.trace,
    )
    trace_token = set_tracer(tracer)

    async with AsyncSessionLocal() as db:
        job_svc = JobService(db)
        with time_job(), workflow_span(job_id):
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

                with tracer(
                    kind="workflow",
                    agent_id="workflow",
                    start_message=f"Job {job_id} starting",
                    end_message="Job complete",
                ) as t:
                    workflow = DocumentationWorkflow(
                        project=project, job=job, db=db, sandbox=sandbox
                    )
                    result = await workflow.run()
                    t.outputs(
                        saved_docs=result.get("saved_doc_ids", []),
                        requires_review=result.get("requires_review", False),
                    )

                # Save trace artifacts to sandbox/trace/
                try:
                    trace_paths = save_trace_artifacts(tracer, sandbox.trace)
                    await job_svc.update_config(job_id, {"trace_paths": trace_paths})
                    logger.info("trace_saved", job_id=job_id, paths=trace_paths)
                except Exception as exc:
                    logger.warning("trace_save_failed", job_id=job_id, error=str(exc))

                if result.get("requires_review"):
                    await job_svc.request_review(job_id)
                    job_total.labels(status="awaiting_review").inc()
                else:
                    await job_svc.complete(job_id)
                    job_total.labels(status="completed").inc()

                await job_svc.write_log(job_id, "coordinator", "info", "Documentation workflow finished")
                return result

            except Exception as exc:
                logger.error("workflow_failed", job_id=job_id, error=str(exc))
                await job_svc.fail(job_id, str(exc))
                job_total.labels(status="failed").inc()
                raise
            finally:
                reset_tracer(trace_token)
