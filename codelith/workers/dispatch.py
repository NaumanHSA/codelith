"""
Starting long work, wherever it is going to run.

Six places in the application hand off a job: analysis, ingestion, composition, the
resumed half of a reviewed composition, a revision, and a document export. All six
used `task.delay(...)`, which is Celery's and only Celery's.

They call `dispatch()` now. In server mode it is `delay` with an extra function call.
In solo mode it puts the task body on the in-process worker instead, and the caller
cannot tell — both return an id to record on the job, and the job row is what the
studio and the CLI poll either way.
"""

from __future__ import annotations

from typing import Any

from codelith.config import get_settings

__all__ = ["dispatch"]


def dispatch(task: Any, *args: Any, **kwargs: Any) -> str:
    """
    Queue `task`, and return the id to store on the job.

    The id is only ever written to `jobs.celery_task_id` and used to revoke a queued
    Celery task. Solo mode returns an `inline-…` id that nothing revokes, which costs
    nothing: cancellation is enforced by the flag the workflow polls, and `revoke`
    was always best-effort — it stops a task that has not started and does nothing to
    one that has.
    """
    if get_settings().CODELITH_PROFILE == "solo":
        from codelith.workers.inline import worker

        return worker.submit(task, args, kwargs)

    return task.delay(*args, **kwargs).id
