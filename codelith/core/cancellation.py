"""
Cooperative job cancellation.

Cancelling used to be cosmetic: `JobService.cancel()` flipped a column, the UI showed
"cancelled", and the worker carried on streaming tokens out of LM Studio until the
document was finished. The user is told one thing and the machine does another.

Real cancellation needs three parts, and this module is the middle one:

  1. the API revokes the Celery task and records the intent (Redis flag + DB status)
  2. the running worker notices — that is `CancellationToken`, polled between agents,
     between sections, and between streamed chunks
  3. the in-flight HTTP request is abandoned mid-generation, which is why LLM calls
     stream rather than waiting for one big response

The work runs on a background thread of this process, so the flag is a set in memory.
It was Redis when the API and a Celery worker were separate processes and the signal
had to cross between them.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

#: Key lives well past the longest plausible job, then expires on its own.
_TTL_SECONDS = 24 * 60 * 60


def _key(job_id: int) -> str:
    return f"job:cancel:{job_id}"


class JobCancelled(Exception):
    """Raised inside a workflow when the user has asked for it to stop."""

    def __init__(self, job_id: int) -> None:
        super().__init__(f"Job {job_id} was cancelled")
        self.job_id = job_id


# ── Where the flag lives ──────────────────────────────────────────────────────
#
# A set in memory. The work runs on a background thread of this process, so the
# signal never has to leave it.
#
# It used to be Redis, because the API and a Celery worker were different processes
# and a module-level flag would never have been seen. That is the only thing Redis
# was doing here.


class _Flags:
    """Cancellation flags for a single process."""

    def __init__(self) -> None:
        self._flagged: set[int] = set()

    async def set(self, job_id: int) -> None:
        self._flagged.add(job_id)

    async def clear(self, job_id: int) -> None:
        self._flagged.discard(job_id)

    async def is_set(self, job_id: int) -> bool:
        return job_id in self._flagged

    async def close(self) -> None:
        return None


#: One process, one set. Held for the life of the interpreter, because a flag that did
#: not outlive the call that set it would signal nothing.
_flags_store = _Flags()


def _flags() -> _Flags:
    return _flags_store


async def request_cancel(job_id: int) -> None:
    """Signal a running job to stop. Safe to call when nothing is running."""
    flags = _flags()
    try:
        await flags.set(job_id)
        logger.info("cancel_requested", job_id=job_id)
    finally:
        await flags.close()


async def clear_cancel(job_id: int) -> None:
    """Drop a stale flag so a re-run of the same job id is not killed at birth."""
    flags = _flags()
    try:
        await flags.clear(job_id)
    finally:
        await flags.close()


async def clear_stale_cancel(job_id: int) -> bool:
    """
    Clear a leftover flag at the start of a run — unless the job is cancelled.

    Clearing unconditionally erases the very signal it exists to deliver, and there
    are two ordinary ways to hit it:

    * **Redelivery.** `task_acks_late=True` means a task interrupted by a worker
      restart goes back on the queue. It comes back, wipes its own cancellation, and
      runs the work the user already stopped.
    * **Cancelling something queued.** The API sets the flag and revokes the task, but
      revoke is best-effort — a worker that has already prefetched the message starts
      anyway, clears the flag, and never sees the request.

    The database is what makes the difference decidable. `JobService.cancel()` writes
    `status="cancelled"` durably, so a flag belonging to a cancelled job is a live
    instruction, and one belonging to any other job is debris. Returns whether the
    flag was cleared.
    """
    from codelith.db.repositories.job_repo import JobRepository
    from codelith.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        job = await JobRepository(db).get_by_id(job_id)

    if job is not None and job.status == "cancelled":
        logger.info("cancel_flag_kept", job_id=job_id, status=job.status)
        return False

    await clear_cancel(job_id)
    return True


class CancellationToken:
    """
    Polled by long-running work to find out whether it should stop.

    Holds one Redis connection for the life of the job and caches the answer briefly,
    so checking between every streamed chunk costs nothing.
    """

    def __init__(self, job_id: int, poll_interval: float = 1.0) -> None:
        self.job_id = job_id
        self.poll_interval = poll_interval
        self._flags: _Flags | None = None
        self._cancelled = False
        self._last_check = 0.0

    async def __aenter__(self) -> CancellationToken:
        self._flags = _flags()
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._flags is not None:
            await self._flags.close()
            self._flags = None

    async def is_cancelled(self) -> bool:
        import time

        if self._cancelled:
            return True
        now = time.monotonic()
        if now - self._last_check < self.poll_interval:
            return False
        self._last_check = now

        if self._flags is None:  # pragma: no cover - defensive
            return False
        try:
            self._cancelled = await self._flags.is_set(self.job_id)
        except Exception as exc:  # pragma: no cover - never block work on the flag store
            logger.warning("cancel_check_failed", job_id=self.job_id, error=str(exc))
            return False
        return self._cancelled

    async def raise_if_cancelled(self) -> None:
        if await self.is_cancelled():
            raise JobCancelled(self.job_id)


#: Set for the duration of a job so agents can reach the token without threading it
#: through every signature.
_current: CancellationToken | None = None


def set_token(token: CancellationToken | None) -> None:
    global _current
    _current = token


def get_token() -> CancellationToken | None:
    return _current


async def check_cancelled() -> None:
    """Raise `JobCancelled` if the active job has been cancelled. No-op otherwise."""
    token = _current
    if token is not None:
        await token.raise_if_cancelled()


__all__ = [
    "CancellationToken",
    "JobCancelled",
    "check_cancelled",
    "clear_cancel",
    "clear_stale_cancel",
    "get_token",
    "request_cancel",
    "set_token",
]
