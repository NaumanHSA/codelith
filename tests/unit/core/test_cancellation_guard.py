"""
Starting a run must not erase the reason it should not run.

Every worker task begins by dropping a leftover cancel flag, so that re-running a job
id is not killed at birth by debris. Done unconditionally, that clears the user's
cancellation as readily as it clears debris — and there are two ordinary ways in:

* **Redelivery.** `task_acks_late=True` puts a task interrupted by a worker restart
  back on the queue. It comes back, wipes its own cancellation, and does the work the
  user already stopped.
* **Cancelling something queued.** `JobService.cancel()` revokes the Celery task, but
  revoke is best-effort: a worker that already prefetched the message starts anyway,
  clears the flag, and never sees the request.

The database decides. `cancel()` writes `status="cancelled"` durably before returning,
so a flag on a cancelled job is a live instruction and a flag on anything else is
debris.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codelith.core import cancellation


@pytest.fixture
def job(monkeypatch):
    """Stands in for the row `clear_stale_cancel` reads, and records the Redis call."""
    state = {"status": "running", "cleared": False, "exists": True}

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _Repo:
        def __init__(self, session):
            pass

        async def get_by_id(self, job_id):
            if not state["exists"]:
                return None
            return SimpleNamespace(id=job_id, status=state["status"])

    async def _clear(job_id):
        state["cleared"] = True

    monkeypatch.setattr(cancellation, "clear_cancel", _clear)
    monkeypatch.setattr("codelith.db.session.AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr("codelith.db.repositories.job_repo.JobRepository", _Repo)
    return state


class TestTheFlagSurvivesWhenItIsRealAnyway:
    async def test_a_cancelled_job_keeps_its_flag(self, job) -> None:
        """The load-bearing case. Clearing here is the bug: the task goes on to run
        work the user stopped, and the UI has already told them it was cancelled."""
        job["status"] = "cancelled"

        cleared = await cancellation.clear_stale_cancel(1)

        assert cleared is False
        assert job["cleared"] is False

    async def test_the_decision_is_reported(self, job) -> None:
        """A job that silently declines to start needs a reason in the log, or the
        next person reads it as the worker losing the message."""
        from structlog.testing import capture_logs

        job["status"] = "cancelled"

        with capture_logs() as logs:
            await cancellation.clear_stale_cancel(1)

        assert any(entry["event"] == "cancel_flag_kept" for entry in logs)


class TestDebrisIsStillCleared:
    @pytest.mark.parametrize("status", ["pending", "running", "failed", "completed"])
    async def test_any_other_status_clears(self, job, status) -> None:
        """The original purpose has to keep working — a leftover flag from a reused id
        would otherwise kill every new run instantly."""
        job["status"] = status

        cleared = await cancellation.clear_stale_cancel(1)

        assert cleared is True
        assert job["cleared"] is True

    async def test_a_job_that_is_not_in_the_database_clears(self, job) -> None:
        """No row means nothing to protect. Refusing to clear would strand the id."""
        job["exists"] = False

        assert await cancellation.clear_stale_cancel(999) is True
        assert job["cleared"] is True
