from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from codelith.config import get_settings

settings = get_settings()

def _engine_kwargs() -> dict:
    """
    Pool settings that mean something for the database in use.

    `pool_size` and `max_overflow` belong to a queue pool in front of a server that
    charges for connections. SQLite is a file: its pool does not accept those
    arguments at all, and a connection costs nothing to open.

    `check_same_thread=False` is required rather than optional. Solo mode runs jobs on
    a background thread (`workers/inline.py`) while the API answers on another, and
    SQLite refuses a connection used from a thread other than the one that made it
    unless told the caller is handling the serialisation — which SQLAlchemy's pool is.
    """
    if settings.DATABASE_URL.startswith("sqlite"):
        _ensure_parent_dir(settings.DATABASE_URL)
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True}


def _ensure_parent_dir(url: str) -> None:
    """
    Make the folder the database file lives in.

    SQLite creates a missing *file* and refuses a missing *directory* — the error is
    `unable to open database file`, which reads like a permissions problem and is
    not. Since the default path is under the user's home and nothing else creates it,
    a first run on a clean machine would fail on its own default.
    """
    from pathlib import Path

    path = url.split("///", 1)[-1]
    if path and path != ":memory:":
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.SQLALCHEMY_ECHO,
    **_engine_kwargs(),
)

def tune_sqlite(dbapi_connection, _record) -> None:
    """
    Two pragmas that decide whether this is usable with more than one connection.

    **WAL.** The default rollback journal takes a lock over the whole database for
    every write, so a reader and a writer block each other — and this design has the
    API answering requests while a background thread writes an analysis. In WAL they
    do not block: readers see the last committed state while a write is in progress.

    **`busy_timeout`.** Without it, a lock that is held for a moment raises "database
    is locked" immediately rather than waiting. Five seconds is far longer than any
    contention here and turns a spurious failure into a pause nobody notices.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    # Foreign keys are off by default in SQLite, which would silently let the
    # `ondelete=CASCADE` the models declare do nothing at all.
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


if settings.DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event

    event.listen(engine.sync_engine, "connect", tune_sqlite)


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)
