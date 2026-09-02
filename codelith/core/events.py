from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from codelith.db.session import engine

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("application_startup")

    # Say which endpoint each tier resolved to, and complain now about anything the
    # chosen providers need and do not have. Both tiers being independently local or
    # hosted makes "which model actually wrote this?" a real question, and an empty
    # OPENAI_API_KEY should not first surface as a 401 forty minutes into an analysis.
    from codelith.llm.providers import configured_specs, missing_configuration

    for tier, spec in configured_specs().items():
        logger.info(
            "llm_tier_configured",
            tier=tier,
            provider=spec.provider,
            model=spec.model,
            base_url=spec.base_url,
            context_window=spec.context_window,
        )
    for problem in missing_configuration():
        logger.warning("llm_configuration_incomplete", problem=problem)

    # Build the schema on first run. There is no separate migrate step to forget:
    # the database is a file this process owns, and an empty one is indistinguishable
    # from a first launch. Existing databases are left alone.
    from codelith.db.bootstrap import ensure_schema

    if await ensure_schema(engine):
        logger.info("database_created", url=engine.url.render_as_string(hide_password=True))

    # Hand back pages a job claimed and never resolved.
    #
    # Every path that ends a run releases them, but no path runs at all if the process
    # is killed outright — and a job in flight when you close the terminal is exactly
    # that. The claim would otherwise outlive the job, and because the studio polls the
    # site map for as long as any page is `generating`, one such page makes the
    # documentation page re-fetch every few seconds for ever.
    #
    # Only pages whose job has already reached a terminal status: if the job is over,
    # nothing is writing its pages.
    from sqlalchemy import text

    from codelith.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text(
                    "UPDATE doc_pages SET status = 'planned' "
                    "WHERE status = 'generating' AND job_id IN ("
                    "  SELECT id FROM jobs WHERE status IN ('completed','failed','cancelled')"
                    ")"
                )
            )
            await db.commit()
            if freed := (result.rowcount or 0):
                logger.info("released_pages_of_finished_jobs", pages=freed)
    except Exception:  # pragma: no cover - never stop the app booting over cleanup
        logger.warning("page_reconciliation_failed", exc_info=True)

    yield
    logger.info("application_shutdown")
    await engine.dispose()
