"""
How a Celery task enters async code.

Every task body is a coroutine, and each of the five task entrypoints used to call
`asyncio.get_event_loop().run_until_complete(...)`. That worked only by accident of
the prefork pool: the forked child's main thread has an implicit event loop, so
`get_event_loop()` returned the same one for the life of the process. Off that path
it breaks in two different ways — in a worker *thread* there is no implicit loop at
all (`RuntimeError: There is no current event loop in thread ...`), and the implicit
loop is deprecated and slated for removal.

`asyncio.run()` is not the fix either, tempting as it looks. It creates and closes a
loop per call, and the things this app holds onto are bound to the loop that created
them: the SQLAlchemy engine's connection pool (`app/db/session.py`) and the
`@lru_cache`d `AsyncOpenAI` client's httpx pool (`app/llm/client.py`). The second task
in a process would inherit pooled connections belonging to a closed loop and fail
somewhere far from here.

So: one loop, created on first use and kept for the life of the thread. That is
exactly the lifetime prefork provided, made explicit and no longer dependent on which
pool the worker happens to be running.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

_local = threading.local()

T = TypeVar("T")


def get_loop() -> asyncio.AbstractEventLoop:
    """The current thread's event loop, created on first use."""
    loop: asyncio.AbstractEventLoop | None = getattr(_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _local.loop = loop
    return loop


def run(coro: Coroutine[Any, Any, T]) -> T:
    """Run a task coroutine to completion on this thread's persistent loop."""
    return get_loop().run_until_complete(coro)


__all__ = ["run", "get_loop"]
