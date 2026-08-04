"""Celery entrypoint for Phase 1 (analysis)."""

import asyncio

import structlog

from app.db.session import AsyncSessionLocal
from app.observability.metrics import job_total, time_job
from app.observability.tracing import workflow_span
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="analysis.run_analysis", bind=True, max_retries=1)
def run_analysis(self, job_id: int, force: bool = False) -> dict:
    return asyncio.get_event_loop().run_until_complete(_run_analysis(job_id, force))


async def _run_analysis(job_id: int, force: bool) -> dict:
    from app.core.sandbox import JobSandbox
    from app.tracing.runtime import (
        create_tracer,
        reset_tracer,
        save_trace_artifacts,
        set_tracer,
    )

    sandbox = JobSandbox(job_id)
    sandbox.setup()
    logger.info("sandbox_ready", job_id=job_id, root=str(sandbox.root))

    tracer = create_tracer(job_id=str(job_id), workflow_type="analysis", run_dir=sandbox.trace)
    trace_token = set_tracer(tracer)

    async with AsyncSessionLocal() as db:
        from app.db.repositories.job_repo import JobRepository
        from app.db.repositories.knowledge import KnowledgeBaseRepository
        from app.db.repositories.project_repo import ProjectRepository
        from app.services.job_service import JobService
        from app.workflows.analysis_workflow import AnalysisWorkflow

        job_svc = JobService(db)
        with time_job(), workflow_span(job_id):
            try:
                job = await JobRepository(db).get_with_steps(job_id)
                if not job:
                    raise ValueError(f"Job {job_id} not found")

                project = await ProjectRepository(db).get_by_id_with_sources(job.project_id)
                if not project:
                    raise ValueError(f"Project {job.project_id} not found")

                await job_svc.write_log(job_id, "coordinator", "info", "Analysis started")

                # Cheap exit: a usable KB already exists and nothing was forced.
                if not force:
                    existing = await KnowledgeBaseRepository(db).get_latest_usable(project.id)
                    if existing is not None:
                        await job_svc.write_log(
                            job_id, "coordinator", "info",
                            f"Reusing knowledge base {existing.id} "
                            f"(commit {existing.commit_sha or 'n/a'}) — pass force to rebuild",
                        )
                        await job_svc.complete(job_id)
                        job_total.labels(status="skipped").inc()
                        return {
                            "kb_id": existing.id,
                            "kb_status": existing.status,
                            "reused": True,
                        }

                with tracer(
                    kind="workflow",
                    agent_id="workflow",
                    start_message=f"Analysis job {job_id} starting",
                    end_message="Analysis complete",
                ) as t:
                    workflow = AnalysisWorkflow(
                        project=project, job=job, db=db, sandbox=sandbox
                    )
                    result = await workflow.run()
                    t.outputs(**{k: v for k, v in result.items() if k != "kb_stats"})

                await job_svc.complete(job_id)
                job_total.labels(status="completed").inc()
                logger.info("analysis_complete", job_id=job_id, runs_dir=str(sandbox.root), **{
                    "kb_id": result.get("kb_id"), "kb_status": result.get("kb_status")
                })
                return {**result, "reused": False}

            except Exception as exc:
                logger.exception("analysis_failed", job_id=job_id)
                await job_svc.fail(job_id, str(exc))
                await job_svc.write_log(job_id, "coordinator", "error", f"Analysis failed: {exc}")
                job_total.labels(status="failed").inc()
                await _mark_kb_failed(db, job_id, str(exc))
                raise

            finally:
                save_trace_artifacts(tracer, sandbox.trace)
                reset_tracer(trace_token)


async def _mark_kb_failed(db, job_id: int, error: str) -> None:
    """Leave no knowledge base stuck in RUNNING after a crash."""
    from sqlalchemy import select

    from app.db.repositories.knowledge import KnowledgeBaseRepository
    from app.knowledge.constants import KBStatus
    from app.models.knowledge import KnowledgeBase

    try:
        repo = KnowledgeBaseRepository(db)
        result = await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.job_id == job_id, KnowledgeBase.status == KBStatus.RUNNING
            )
        )
        for kb in result.scalars().all():
            await repo.finish_build(kb.id, status=KBStatus.FAILED, error=error)
        await db.commit()
    except Exception:  # pragma: no cover - best effort during failure handling
        logger.warning("kb_failure_marking_failed", job_id=job_id)
