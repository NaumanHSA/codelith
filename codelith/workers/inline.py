"""
A worker, without a worker.

Server mode hands long work to Celery: the API returns immediately and a separate
process does the writing. Solo mode has no broker and no second process, so the work
happens here — on one background thread, one job at a time.

**One thread, not one per job.** The thread is the unit that owns an event loop, and
the loop is what the SQLAlchemy connection pool and the `AsyncOpenAI` client's httpx
pool are bound to (see `workers/runner.py`). A thread per job would build those pools
again for every run and hand the second job connections belonging to a loop that had
gone. One long-lived thread is precisely the lifetime the prefork worker provided.

Serial is also the honest setting rather than a limitation: server mode already runs
`--pool=solo`, because one LM Studio instance answers requests one at a time. Two
concurrent analyses on one machine would not be twice as fast; they would be the same
work, interleaved, against the same model.

**What is given up.** A queue that lives in a process dies with it. There is no
redelivery, no `task_acks_late`, and a job in flight when the process stops is
abandoned — its pages stay claimed until the reconciliation at next start hands them
back. For one person on one machine that is the right trade: the alternative is
running a broker to protect against closing your own laptop.
"""

from __future__ import annotations

import queue
import threading
import uuid
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class InlineWorker:
    """Runs task bodies on a single background thread, in submission order."""

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[str, Any, tuple, dict]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def submit(self, task: Any, args: tuple = (), kwargs: dict | None = None) -> str:
        """
        Queue a task body and return an id to record on the job.

        The id is not a Celery task id and nothing can revoke it — cancellation in
        solo mode goes through the same flag the workflow polls, which is where it
        was always actually enforced. Celery's `revoke` only ever stopped a task that
        had not started.
        """
        ident = f"inline-{uuid.uuid4()}"
        self._ensure_thread()
        self._queue.put((ident, task, args, kwargs or {}))
        logger.info("inline_task_queued", task=getattr(task, "name", str(task)), id=ident)
        return ident

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._loop, name="codelith-inline-worker", daemon=True
            )
            self._thread.start()

    def _loop(self) -> None:
        while True:
            ident, task, args, kwargs = self._queue.get()
            name = getattr(task, "name", str(task))
            try:
                # `apply` runs the task body in this thread and handles `bind=True`,
                # so the same function serves both profiles. `runner.run` inside it
                # finds this thread's persistent loop.
                task.apply(args=args, kwargs=kwargs, throw=True)
                logger.info("inline_task_finished", task=name, id=ident)
            except Exception:
                # The task has already recorded its own failure on the job row; this
                # thread must survive it, or one bad job ends every later one.
                logger.exception("inline_task_failed", task=name, id=ident)
            finally:
                self._queue.task_done()

    def wait_idle(self, timeout: float | None = None) -> None:
        """Block until the queue drains. For tests and for `codelith analyse`."""
        self._queue.join()


#: One per process, because one process is the whole point.
worker = InlineWorker()
