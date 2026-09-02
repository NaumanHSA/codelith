"""Celery entrypoint for a revision — a targeted edit to prose that already exists."""

import structlog

from codelith.db.session import AsyncSessionLocal
from codelith.observability.metrics import job_total, time_job
from codelith.observability.tracing import workflow_span
from codelith.workers import runner
from codelith.workers.task import task

logger = structlog.get_logger(__name__)


@task("revision.run_revision")
def run_revision(job_id: int) -> dict:
    return runner.run(_run_revision(job_id))


async def _run_revision(job_id: int) -> dict:
    from codelith.core.sandbox import JobSandbox
    from codelith.tracing.artifacts import (
        create_artifact_writer,
        reset_artifact_writer,
        set_artifact_writer,
    )
    from codelith.tracing.runtime import (
        create_tracer,
        reset_tracer,
        save_trace_artifacts,
        set_tracer,
    )

    sandbox = JobSandbox(job_id)
    sandbox.setup()

    tracer = create_tracer(job_id=str(job_id), workflow_type="revision", run_dir=sandbox.trace)
    trace_token = set_tracer(tracer)
    artifact_token = set_artifact_writer(create_artifact_writer(sandbox.artifacts))

    from codelith.core.cancellation import (
        CancellationToken,
        JobCancelled,
        clear_stale_cancel,
        set_token,
    )

    # A stale flag from a previous job with this id would kill the new run instantly —
    # but a flag belonging to *this* job is the user's cancellation, and clearing it
    # would run work they already stopped. See `clear_stale_cancel`.
    await clear_stale_cancel(job_id)

    async with AsyncSessionLocal() as db, CancellationToken(job_id) as token:
        set_token(token)
        from codelith.apps.documentation.services.revision_service import RevisionService
        from codelith.apps.documentation.workflows.revision_workflow import RevisionWorkflow
        from codelith.db.repositories.job_repo import JobRepository
        from codelith.db.repositories.project_repo import ProjectRepository
        from codelith.services.job_service import JobService

        job_svc = JobService(db)
        with time_job(), workflow_span(job_id):
            try:
                job = await JobRepository(db).get_with_steps(job_id)
                if not job:
                    raise ValueError(f"Job {job_id} not found")

                project = await ProjectRepository(db).get_by_id_with_sources(job.project_id)
                if not project:
                    raise ValueError(f"Project {job.project_id} not found")

                config = job.config_json or {}
                await job_svc.write_log(
                    job_id,
                    "coordinator",
                    "info",
                    f"Revising {config.get('address')}"
                    + (f" — {config['anchor']}" if config.get("anchor") else " (whole page)"),
                )

                # The page and everything the reviser needs to see around it. Loaded
                # here rather than in a graph node so a page that has vanished or is
                # busy fails before any model is called.
                page, context = await RevisionService(db).load_target(job)

                with tracer(
                    kind="workflow",
                    agent_id="workflow",
                    start_message=f"Revision job {job_id} starting",
                    end_message="Revision complete",
                ) as t:
                    workflow = RevisionWorkflow(
                        project=project, job=job, db=db, sandbox=sandbox
                    )
                    result = await workflow.run(page=page, context=context)
                    t.outputs(**result)

                if result.get("error"):
                    # The reviser refused — an ambiguous anchor, or a model that
                    # returned nothing. The page is untouched, and saying so is more
                    # use than a green tick over an unchanged document.
                    await job_svc.fail(job_id, result["error"])
                    job_total.labels(status="failed").inc()
                    return result

                # The heading was renamed because the revision made the old one wrong.
                # Every turn of this conversation is keyed on the anchor, so they move
                # with it — otherwise reopening the section finds nothing and the next
                # turn is handed no history.
                if moved := result.get("new_anchor"):
                    svc = RevisionService(db)
                    # Captured before the re-key, which overwrites this job's own
                    # `anchor` with the new one — after it, nothing records what the
                    # heading was called and there is no way to find links to it.
                    was = (job.config_json or {}).get("anchor")
                    turns = await svc.rekey_anchor(job, moved)
                    await job_svc.write_log(
                        job_id,
                        "coordinator",
                        "info",
                        f"Heading renamed — moved {turns} turn(s) of this conversation "
                        f"onto '{moved}'",
                    )
                    # Runs after the publisher, so the renamed page is already stored
                    # and this is the last thing still pointing at the old anchor:
                    # links from elsewhere in the site, which the linker never sees.
                    if pages := await svc.repoint_links(job, was, moved):
                        await job_svc.write_log(
                            job_id,
                            "coordinator",
                            "info",
                            "Repointed links into the renamed heading on: "
                            + ", ".join(pages),
                        )

                await job_svc.complete(job_id)
                job_total.labels(status="completed").inc()
                logger.info(
                    "revision_complete",
                    job_id=job_id,
                    pages=len(result.get("saved_page_ids", [])),
                    runs_dir=str(sandbox.root),
                )
                return result

            except JobCancelled:
                # Nothing is published, so the page still says what it said before.
                logger.info("revision_cancelled", job_id=job_id)
                await job_svc.write_log(
                    job_id, "coordinator", "warning", "Revision cancelled by user"
                )
                job_total.labels(status="cancelled").inc()
                return {"saved_page_ids": [], "cancelled": True}

            except Exception as exc:
                logger.exception("revision_failed", job_id=job_id)
                await job_svc.fail(job_id, str(exc))
                await job_svc.write_log(job_id, "coordinator", "error", f"Revision failed: {exc}")
                job_total.labels(status="failed").inc()
                raise

            finally:
                set_token(None)
                save_trace_artifacts(tracer, sandbox.trace)
                reset_tracer(trace_token)
                reset_artifact_writer(artifact_token)
