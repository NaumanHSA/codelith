"""
What a background task is, now that there is no broker.

Celery gave every long job a decorator, a name, and an `apply()` that runs the body
in the current process. Only the last of those was load-bearing here: one machine
does not need a broker to run its own work, and the queue it published to had exactly
one consumer.

So this is the same three things, in thirty lines. `dispatch()` and the inline worker
were written against `.name` and `.apply()` and did not change when Celery went.

**What went with it.** Redelivery — a task interrupted by the process stopping is not
retried, it is gone. `task_acks_late`, revocation, retries and routing all went too.
For a single machine that is the right trade: the alternative is running a broker to
guard against closing your own laptop, and the reconciliation at startup already
hands back the pages an interrupted job had claimed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = ["Task", "task"]


class Task:
    """A named callable that can be run now or handed to the worker thread."""

    def __init__(self, name: str, fn: Callable[..., Any]) -> None:
        self.name = name
        self.fn = fn
        self.__doc__ = fn.__doc__
        self.__name__ = getattr(fn, "__name__", name)

    def apply(self, args: tuple = (), kwargs: dict | None = None, throw: bool = False) -> Any:
        """
        Run the body here and now.

        `throw` is accepted and ignored — it exists because the inline worker passes
        it, and it passes it because this method used to be Celery's, where the
        default was to swallow the exception. Here an exception always propagates and
        the worker thread logs it.
        """
        return self.fn(*args, **(kwargs or {}))

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.fn(*args, **kwargs)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<Task {self.name}>"


def task(name: str) -> Callable[[Callable[..., Any]], Task]:
    """Name a function so a queued job can be identified in a log."""

    def decorate(fn: Callable[..., Any]) -> Task:
        return Task(name, fn)

    return decorate
