import logging
import sys

import structlog

from codelith.config import get_settings


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
    _error_level = (
        "uvicorn.access",
        "sqlalchemy.engine", "sqlalchemy.engine.Engine", "sqlalchemy.pool",
    )
    _warning_level = (
        "httpx", "httpcore", "httpcore.http11", "httpcore.connection",
        "openai._base_client", "openai.http_client",
        "git", "git.cmd", "git.repo",
        "pydot",
        "langgraph",
    )
    for name in _error_level:
        logging.getLogger(name).setLevel(logging.ERROR)
    for name in _warning_level:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)
