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
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True}


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.SQLALCHEMY_ECHO,
    **_engine_kwargs(),
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)
