from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "document-anything",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks.ingestion_tasks",
        "app.workers.tasks.generation_tasks",
        "app.workers.tasks.export_tasks",
    ],
)

from celery.signals import worker_process_init


@worker_process_init.connect
def init_worker_logging(**kwargs):
    from app.core.logging import setup_logging
    setup_logging()


celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.workers.tasks.ingestion_tasks.*": {"queue": "ingestion"},
        "app.workers.tasks.generation_tasks.*": {"queue": "generation"},
        "app.workers.tasks.export_tasks.*": {"queue": "export"},
    },
)
