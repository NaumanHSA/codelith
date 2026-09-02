"""
Starting long work, in a process that has a worker and in one that does not.

Six places hand off a job — analysis, ingestion, composition, the resumed half of a
reviewed composition, a revision, a document export — and all six used `.delay()`,
which is Celery's and only Celery's. They go through `dispatch()` now, and the caller
cannot tell which profile it is on: both return an id to record on the job.

What is actually worth pinning is the inline worker's behaviour under failure. It is
one thread serving every job in the process, so an exception that escapes it does not
fail one job — it ends every job after it, silently, for the life of the process.
"""

from __future__ import annotations

import pytest

from codelith.config import get_settings
from codelith.workers.dispatch import dispatch
from codelith.workers.inline import InlineWorker


class _Recorder:
    """Stands in for a Celery task. `apply` is what runs the body in-process."""

    name = "fake.task"

    def __init__(self, ran: list, explode: bool = False) -> None:
        self._ran = ran
        self._explode = explode

    def apply(self, args=(), kwargs=None, throw=False):
        if self._explode:
            raise RuntimeError("boom")
        self._ran.append((args, kwargs or {}))

    def delay(self, *args, **kwargs):
        self._ran.append(("delay", args, kwargs))

        class _Result:
            id = "celery-123"

        return _Result()


@pytest.fixture
def solo(monkeypatch):
    monkeypatch.setenv("CODELITH_PROFILE", "solo")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


class TestTheInlineWorker:
    def test_it_runs_what_it_is_given(self) -> None:
        ran: list = []
        w = InlineWorker()
        w.submit(_Recorder(ran), (7,), {"force": True})
        w.wait_idle()
        assert ran == [((7,), {"force": True})]

    def test_one_failing_job_does_not_end_every_later_one(self) -> None:
        """
        The thread is shared by every job in the process. An exception that escapes
        the loop would take out the queue, and nothing afterwards would ever run —
        the failure mode being guarded against is silence, not an error.
        """
        ran: list = []
        w = InlineWorker()
        w.submit(_Recorder(ran, explode=True), (1,))
        w.submit(_Recorder(ran), (2,))
        w.wait_idle()
        assert ran == [((2,), {})]

    def test_order_is_submission_order(self) -> None:
        """
        Serial on purpose. One LM Studio answers one request at a time, so two
        concurrent analyses would be the same work interleaved, against the same
        model — and would rebuild the connection pools bound to this thread's loop.
        """
        ran: list = []
        w = InlineWorker()
        for i in range(5):
            w.submit(_Recorder(ran), (i,))
        w.wait_idle()
        assert [a[0][0] for a in ran] == [0, 1, 2, 3, 4]

    def test_the_thread_is_started_lazily_and_reused(self) -> None:
        w = InlineWorker()
        assert w._thread is None, "a process that queues nothing starts no thread"
        ran: list = []
        w.submit(_Recorder(ran), (1,))
        w.wait_idle()
        first = w._thread
        w.submit(_Recorder(ran), (2,))
        w.wait_idle()
        assert w._thread is first, "a second job must not build a second loop"


class TestDispatch:
    def test_solo_runs_it_here(self, solo) -> None:
        ran: list = []
        task = _Recorder(ran)
        ident = dispatch(task, 7)

        from codelith.workers.inline import worker

        worker.wait_idle()
        assert ident.startswith("inline-")
        assert ran == [((7,), {})]

    def test_server_hands_it_to_celery(self, monkeypatch) -> None:
        monkeypatch.setenv("CODELITH_PROFILE", "server")
        get_settings.cache_clear()
        try:
            ran: list = []
            assert dispatch(_Recorder(ran), 7, force=True) == "celery-123"
            assert ran == [("delay", (7,), {"force": True})]
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()
