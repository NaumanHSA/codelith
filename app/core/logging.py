import logging
import sys
import structlog
from app.config import get_settings


def setup_logging() -> None:
    settings = get_settings()

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.is_production:
        processors = shared_processors + [structlog.processors.JSONRenderer()]
        log_level = logging.INFO
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
        log_level = logging.DEBUG

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=log_level, stream=sys.stdout, format="%(message)s")
    # Quiet noisy libs
    for name in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)
