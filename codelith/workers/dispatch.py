"""
Starting long work.

Six places hand off a job — analysis, ingestion, composition, the resumed half of a
reviewed composition, a revision, a document export. They used to call Celery's
`.delay()`; then a `dispatch()` that chose between Celery and an in-process worker;
now there is one worker and this is the door to it.

Kept as a function rather than inlined at the six call sites because they should not
know how work is scheduled — only that it has been.
"""

from __future__ import annotations

from typing import Any

__all__ = ["dispatch"]


def dispatch(task: Any, *args: Any, **kwargs: Any) -> str:
    """
    Queue `task`, and return the id to store on the job.

    The id identifies the run in a log. Nothing revokes it: cancellation is enforced
    by the flag the workflow polls, which is where it was always actually enforced —
    Celery's `revoke` only ever stopped a task that had not started.
    """
    from codelith.workers.inline import worker

    return worker.submit(task, args, kwargs)
