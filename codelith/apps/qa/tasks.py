"""The worker's entry for a QA run."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from codelith.db.session import AsyncSessionLocal
from codelith.workers import runner
from codelith.workers.task import task

logger = structlog.get_logger(__name__)


@task("qa.run")
def run_qa(run_id: int) -> dict:
    return runner.run(_run(run_id))


async def _run(run_id: int) -> dict:
    from codelith.apps.qa.service import QAService
    from codelith.core.cancellation import (
        CancellationToken,
        JobCancelled,
        clear_stale_cancel,
        set_token,
    )
    from codelith.models.qa import QARun
    from codelith.services.job_service import JobService

    async with AsyncSessionLocal() as db:
        run = await db.get(QARun, run_id)
        if run is None:
            raise ValueError(f"QA run {run_id} not found")
        job_id = run.job_id
    if job_id:
        await clear_stale_cancel(job_id)

    async with AsyncSessionLocal() as db, CancellationToken(job_id or 0) as token:
        set_token(token if job_id else None)
        jobs = JobService(db)
        service = QAService(db)
        try:
            done = await service.execute(run_id, token if job_id else None)
            if job_id:
                await jobs.complete(job_id)
            logger.info("qa_complete", run_id=run_id, findings=(done.summary_json or {}).get("total"))
            return {"run_id": run_id, "findings": (done.summary_json or {}).get("total", 0)}
        except JobCancelled:
            await db.rollback()
            run = await db.get(QARun, run_id)
            if run is not None:
                run.status, run.finished_at = "cancelled", datetime.now(UTC)
                await db.commit()
            if job_id:
                await jobs.write_log(job_id, "qa", "warning", "QA run cancelled")
            logger.info("qa_cancelled", run_id=run_id)
            return {"run_id": run_id, "cancelled": True}
        except Exception as exc:
            logger.exception("qa_failed", run_id=run_id)
            await db.rollback()
            run = await db.get(QARun, run_id)
            message = getattr(exc, "message", None) or str(exc)
            if run is not None:
                run.status, run.error, run.finished_at = "failed", message, datetime.now(UTC)
                await db.commit()
            if job_id:
                await jobs.fail(job_id, message)
                await jobs.write_log(job_id, "qa", "error", f"QA run failed: {message}")
            return {"run_id": run_id, "error": message}
        finally:
            set_token(None)


__all__ = ["run_qa"]
