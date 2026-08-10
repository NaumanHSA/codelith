import sys

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "codelith",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks.ingestion_tasks",
        "app.workers.tasks.analysis_tasks",
        "app.workers.tasks.composition_tasks",
        "app.workers.tasks.revision_tasks",
        "app.workers.tasks.generation_tasks",
        "app.workers.tasks.export_tasks",
    ],
)

from celery.signals import worker_init, worker_process_init


# `worker_process_init` fires per forked child and never fires at all under the
# threads pool, which would leave a Windows worker logging unformatted. `worker_init`
# fires in the worker process for every pool. Both are connected because prefork
# children need their own call, and `setup_logging` is idempotent — it reconfigures
# structlog, so a second call in the parent costs nothing.
@worker_init.connect
@worker_process_init.connect
def init_worker_logging(**kwargs):
    from app.core.logging import setup_logging
    setup_logging()


# The prefork pool needs fork(). Windows has none, so the pool spawns instead and the
# child never inherits the module globals `celery.app.trace.fast_trace_task` reads —
# every task dies on pickup with "not enough values to unpack (expected 3, got 0)"
# while the worker itself reports ready. That gap is the trap: a booting worker that
# has printed its queues and its task list looks identical to a working one.
#
# `solo` rather than `threads`, because two process-wide singletons are bound to the
# event loop that created them — the SQLAlchemy engine's connection pool
# (`app/db/session.py`) and the `@lru_cache`d `AsyncOpenAI` client's httpx pool
# (`app/llm/client.py`). A thread pool gives each worker thread its own loop, so those
# pools would be shared across loops; making them thread-local is a real refactor and
# buys nothing here, because one LM Studio instance serves requests serially anyway.
# Concurrency *within* a job is untouched — `asyncio.gather` over narratives and
# sections all happens inside the single task.
#
# Set as config rather than a `--pool` flag so it reaches every entry point —
# `dev.sh`, `make worker`, a bare `celery ... worker`. Celery only overrides the CLI
# when that CLI value is the default `prefork`, so an explicit `--pool=X` still wins.
if sys.platform == "win32":
    celery_app.conf.worker_pool = "solo"

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Routes match the task NAME, not the module path — the tasks are registered
    # as "ingestion.*" / "generation.*" / "export.*" via @celery_app.task(name=...).
    task_routes={
        "ingestion.*": {"queue": "ingestion"},
        # Analysis is ingestion-shaped work (clone, parse, embed), so it shares that
        # queue rather than needing a new worker to be started.
        "analysis.*": {"queue": "ingestion"},
        # Composition is generation-shaped work and shares that queue.
        "composition.*": {"queue": "generation"},
        # A revision is one writing call against a page that exists. Same queue:
        # it competes for the same model, and a separate one would only let a
        # revision jump ahead of the composition whose output it edits.
        "revision.*": {"queue": "generation"},
        "generation.*": {"queue": "generation"},
        "export.*": {"queue": "export"},
    },
)
