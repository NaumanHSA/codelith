import structlog

from app.db.session import AsyncSessionLocal
from app.observability.metrics import job_total, time_job
from app.observability.tracing import workflow_span
from app.services.job_service import JobService
from app.workers import runner
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="generation.run_documentation_workflow", bind=True, max_retries=1)
def run_documentation_workflow(self, job_id: int) -> dict:
    return runner.run(_run_workflow(job_id))


async def _run_workflow(job_id: int) -> dict:
    from app.core.sandbox import JobSandbox
    from app.tracing.artifacts import (
        create_artifact_writer,
        reset_artifact_writer,
        set_artifact_writer,
    )
    from app.tracing.runtime import create_tracer, reset_tracer, save_trace_artifacts, set_tracer

    sandbox = JobSandbox(job_id)
    sandbox.setup()
    logger.info("sandbox_ready", job_id=job_id, root=str(sandbox.root))

    tracer = create_tracer(
        job_id=str(job_id),
        workflow_type="documentation",
        run_dir=sandbox.trace,
    )
    trace_token = set_tracer(tracer)

    # Artifacts record what each stage produced, not just that it ran.
    artifact_token = set_artifact_writer(create_artifact_writer(sandbox.artifacts))

    async with AsyncSessionLocal() as db:
        job_svc = JobService(db)
        with time_job(), workflow_span(job_id):
            try:
                from app.db.repositories.job_repo import JobRepository
                from app.db.repositories.project_repo import ProjectRepository
                from app.workflows.documentation_workflow import DocumentationWorkflow

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

                logger.info("job_complete", job_id=job_id, runs_dir=str(sandbox.root))

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
                # Use a fresh session — the current one may be in a rolled-back state
                # from a failed flush inside an agent (e.g. concurrent writer sessions).
                try:
                    async with AsyncSessionLocal() as err_db:
                        await JobService(err_db).fail(job_id, str(exc))
                except Exception as fail_exc:
                    logger.error("job_fail_update_failed", job_id=job_id, error=str(fail_exc))
                job_total.labels(status="failed").inc()
                raise
            finally:
                reset_tracer(trace_token)
                reset_artifact_writer(artifact_token)
