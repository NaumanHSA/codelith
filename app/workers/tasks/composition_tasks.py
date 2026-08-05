"""Celery entrypoint for Phase 2 (composition)."""

import asyncio

import structlog

from app.db.session import AsyncSessionLocal
from app.observability.metrics import job_total, time_job
from app.observability.tracing import workflow_span
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="composition.run_composition", bind=True, max_retries=1)
def run_composition(self, job_id: int) -> dict:
    return asyncio.get_event_loop().run_until_complete(_run_composition(job_id))


async def _run_composition(job_id: int) -> dict:
    from app.core.sandbox import JobSandbox
    from app.tracing.runtime import (
        create_tracer,
        reset_tracer,
        save_trace_artifacts,
        set_tracer,
    )

    sandbox = JobSandbox(job_id)
    sandbox.setup()

    tracer = create_tracer(job_id=str(job_id), workflow_type="composition", run_dir=sandbox.trace)
    trace_token = set_tracer(tracer)

    from app.core.cancellation import (
        CancellationToken,
        JobCancelled,
        clear_cancel,
        set_token,
    )

    await clear_cancel(job_id)

    async with AsyncSessionLocal() as db, CancellationToken(job_id) as token:
        set_token(token)
        from app.db.repositories.job_repo import JobRepository
        from app.db.repositories.project_repo import ProjectRepository
        from app.services.job_service import JobService
        from app.workflows.composition_workflow import CompositionWorkflow

        job_svc = JobService(db)
        with time_job(), workflow_span(job_id):
            try:
                job = await JobRepository(db).get_with_steps(job_id)
                if not job:
                    raise ValueError(f"Job {job_id} not found")

                project = await ProjectRepository(db).get_by_id_with_sources(job.project_id)
                if not project:
                    raise ValueError(f"Project {job.project_id} not found")

                await job_svc.write_log(job_id, "coordinator", "info", "Composition started")

                with tracer(
                    kind="workflow",
                    agent_id="workflow",
                    start_message=f"Composition job {job_id} starting",
                    end_message="Composition complete",
                ) as t:
                    workflow = CompositionWorkflow(
                        project=project, job=job, db=db, sandbox=sandbox
                    )
                    result = await workflow.run()
                    t.outputs(**result)

                if result.get("requires_review"):
                    await job_svc.request_review(job_id)
                    job_total.labels(status="awaiting_review").inc()
                else:
                    await job_svc.complete(job_id)
                    job_total.labels(status="completed").inc()

                logger.info(
                    "composition_complete",
                    job_id=job_id,
                    docs=len(result.get("saved_doc_ids", [])),
                    runs_dir=str(sandbox.root),
                )
                return result

            except JobCancelled:
                # Nothing is published: a half-written document is worse than none.
                logger.info("composition_cancelled", job_id=job_id)
                await job_svc.write_log(
                    job_id, "coordinator", "warning", "Composition cancelled by user"
                )
                job_total.labels(status="cancelled").inc()
                return {"saved_doc_ids": [], "requires_review": False, "cancelled": True}

            except Exception as exc:
                logger.exception("composition_failed", job_id=job_id)
                await job_svc.fail(job_id, str(exc))
                await job_svc.write_log(
                    job_id, "coordinator", "error", f"Composition failed: {exc}"
                )
                job_total.labels(status="failed").inc()
                raise

            finally:
                set_token(None)
                save_trace_artifacts(tracer, sandbox.trace)
                reset_tracer(trace_token)
