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


def _quietly(log, event: str, **fields: Any) -> None:
    """
    Log, and never raise doing it.

    A logger is not usually a thing that throws. This one has: `structlog` is
    configured with `PrintLoggerFactory(sys.stdout)`, so it writes to whatever stream
    stdout was at configuration time — and a Windows console at cp1252 cannot encode
    everything handed to it (the tracing sink hit exactly that on a `▶`, nine minutes
    into a run), while a redirected stream can be closed underneath it.

    The loop below is one thread serving every job in the process. An exception that
    escapes it does not fail one job — it ends every job after it, silently, for the
    life of the process. Logging is the least important thing happening here and must
    never be the thing that stops it.
    """
    try:
        log(event, **fields)
    except Exception:  # noqa: BLE001 - deliberately the end of the line
        pass


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
        # Quietly, and after the `put`: this runs on the caller's thread — a request
        # handler — and a logger that throws here would fail the request for a job
        # that has in fact been queued.
        _quietly(logger.info, "inline_task_queued", task=getattr(task, "name", str(task)), id=ident)
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
        """
        The thread, which must not end.

        Both guards are here because the failure mode is *silence*. A thread that dies
        does not fail the job it was running — that job has already recorded its own
        failure on the job row — it fails every job submitted afterwards, which then sit
        in the queue with nothing to take them, and a caller waiting on the queue waits
        for ever.
        """
        while True:
            try:
                self._run_one()
            except Exception:  # pragma: no cover - nothing is allowed past here
                _quietly(logger.exception, "inline_worker_recovered")

    def _run_one(self) -> None:
        ident, task, args, kwargs = self._queue.get()
        name = getattr(task, "name", str(task))
        try:
            # `apply` runs the task body in this thread and handles `bind=True`.
            # `runner.run` inside it finds this thread's persistent loop.
            task.apply(args=args, kwargs=kwargs, throw=True)
            _quietly(logger.info, "inline_task_finished", task=name, id=ident)
        except Exception:
            # The task has already recorded its own failure on the job row; this
            # thread must survive it, or one bad job ends every later one.
            _quietly(logger.exception, "inline_task_failed", task=name, id=ident)
        finally:
            # Before anything else can go wrong. A missed `task_done` is not a lost
            # log line, it is a `wait_idle` that never returns.
            self._queue.task_done()

    def wait_idle(self, timeout: float | None = None) -> bool:
        """
        Block until the queue drains. `True` if it did, `False` if `timeout` elapsed.

        `queue.join()` takes no timeout, so this waits on the same condition by hand.
        A caller that asked for a bound and silently got an unbounded wait is worse off
        than one that never asked.
        """
        with self._queue.all_tasks_done:
            return self._queue.all_tasks_done.wait_for(
                lambda: self._queue.unfinished_tasks == 0, timeout
            )


#: One per process, because one process is the whole point.
worker = InlineWorker()
