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

    def test_a_failing_logger_does_not_end_the_queue_either(self, monkeypatch) -> None:
        """
        The hole the first guard left. `except Exception` wrapped the task, but the
        `logger.exception` reporting it sat *inside* that handler — so a logger that
        threw took the thread with it, and every job after that one waited for ever.

        Not hypothetical: structlog writes to whatever `sys.stdout` was at
        configuration time, a Windows console at cp1252 cannot encode everything it is
        handed, and a redirected stream can be closed underneath it. The suite found
        this by hanging, which is exactly how it would present in production.
        """

        class _BrokenLogger:
            def __getattr__(self, _name):
                def _explode(*_args, **_kwargs):
                    raise ValueError("I/O operation on closed file")

                return _explode

        monkeypatch.setattr("codelith.workers.inline.logger", _BrokenLogger())

        ran: list = []
        w = InlineWorker()
        w.submit(_Recorder(ran, explode=True), (1,))
        w.submit(_Recorder(ran), (2,))

        assert w.wait_idle(timeout=5), "the queue must drain even when logging cannot"
        assert ran == [((2,), {})]

    def test_wait_idle_honours_its_timeout(self) -> None:
        """
        It used to take the argument and ignore it — `queue.join()` has no timeout. A
        caller that asked for a bound and silently got an unbounded wait is worse off
        than one that never asked.
        """
        w = InlineWorker()
        w._queue.put(("never", _Recorder([]), (), {}))  # queued behind no thread

        assert w.wait_idle(timeout=0.05) is False

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
    def test_it_runs_the_work_here(self) -> None:
        """
        One door. There was a second — `task.delay()` to a Celery broker — chosen by
        a `CODELITH_PROFILE` setting. Both are gone, and so is the setting.
        """
        ran: list = []
        ident = dispatch(_Recorder(ran), 7, force=True)

        from codelith.workers.inline import worker

        worker.wait_idle()
        assert ident.startswith("inline-")
        assert ran == [((7,), {"force": True})]
