"""
Shared test configuration.

Deliberately free of database *setup*: unit tests must run with no infrastructure, as
`make test-unit` advertises, and everything that needs a schema lives in
`tests/integration/conftest.py`.

But "no setup" is not the same as "never touches a database", and the difference cost
a real bug. Two things are handled here, both discovered by the suite refusing to end.

**Tests must not write to the developer's own knowledge base.** `codelith/db/session.py`
builds its engine at import time from `CODELITH_HOME`, and some code opens a session of
its own without being handed one — `BaseAgent._emit_log_isolated` does, deliberately,
because a progress line from inside `asyncio.gather` cannot borrow the agent's session.
It also swallows its own failures, so a unit test that reached the real `~/.codelith`
did so silently. `CODELITH_HOME` is redirected before anything imports that module.

**The engine has to be disposed or the process never exits.** `aiosqlite` runs every
connection on its own **non-daemon** thread. One session opened anywhere in the run
leaves one of those behind, and a non-daemon thread blocks interpreter exit — so pytest
printed `1119 passed` and then hung for ever, which meant `make test` never returned.
The tests were fine; the process was not.

Event-loop scoping is configured in `pyproject.toml`
(`asyncio_default_*_loop_scope`); pytest-asyncio 1.x no longer supports overriding
the `event_loop` fixture here.
"""

import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest_asyncio

#: A home of its own, per run. Set unconditionally rather than with `setdefault`: a
#: developer with `CODELITH_HOME` exported for their own work is exactly the person
#: this protects, and honouring it here would point the suite at their real database.
#:
#: This must happen at import, before any test module imports `codelith.db.session`.
#: conftest is imported first, which is what makes that ordering reliable.
_TEST_HOME = Path(tempfile.gettempdir()) / f"codelith-test-home-{uuid.uuid4().hex}"
os.environ["CODELITH_HOME"] = str(_TEST_HOME)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _release_the_application_engine():
    """
    Dispose the engine the application module created at import.

    Autouse and session-scoped because the leak does not belong to any one test: any
    test that reaches a code path opening its own session creates the connection, and
    which test that is changes as the suite grows. Disposing once at the end is the
    only version of this that stays true.

    Best effort on the way out. A temporary directory that will not delete — on
    Windows a connection may still be closing — must not fail a suite that passed.
    """
    yield

    from codelith.db.session import engine

    await engine.dispose()
    shutil.rmtree(_TEST_HOME, ignore_errors=True)
