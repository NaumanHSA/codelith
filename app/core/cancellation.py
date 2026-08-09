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

Redis is the signalling channel because the API process and the Celery worker are
different processes; a module-level flag would never be seen.
"""

from __future__ import annotations

import structlog
from redis.asyncio import Redis

from app.config import get_settings

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


async def request_cancel(job_id: int) -> None:
    """Signal a running job to stop. Safe to call when nothing is running."""
    redis = Redis.from_url(get_settings().REDIS_URL)
    try:
        await redis.set(_key(job_id), "1", ex=_TTL_SECONDS)
        logger.info("cancel_requested", job_id=job_id)
    finally:
        await redis.aclose()


async def clear_cancel(job_id: int) -> None:
    """Drop a stale flag so a re-run of the same job id is not killed at birth."""
    redis = Redis.from_url(get_settings().REDIS_URL)
    try:
        await redis.delete(_key(job_id))
    finally:
        await redis.aclose()


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
    from app.db.repositories.job_repo import JobRepository
    from app.db.session import AsyncSessionLocal

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
        self._redis: Redis | None = None
        self._cancelled = False
        self._last_check = 0.0

    async def __aenter__(self) -> CancellationToken:
        self._redis = Redis.from_url(get_settings().REDIS_URL)
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def is_cancelled(self) -> bool:
        import time

        if self._cancelled:
            return True
        now = time.monotonic()
        if now - self._last_check < self.poll_interval:
            return False
        self._last_check = now

        if self._redis is None:  # pragma: no cover - defensive
            return False
        try:
            self._cancelled = bool(await self._redis.exists(_key(self.job_id)))
        except Exception as exc:  # pragma: no cover - never block work on Redis
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
