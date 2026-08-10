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

    # Create tables if they don't exist (dev only — prod uses Alembic)
    # async with engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)
    yield
    logger.info("application_shutdown")
    await engine.dispose()
