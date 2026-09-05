from fastapi import FastAPI

from codelith.api.v1.router import v1_router
from codelith.config import get_settings
from codelith.core.events import lifespan
from codelith.core.exceptions import register_exception_handlers
from codelith.core.logging import setup_logging
from codelith.core.middleware import register_middleware

setup_logging()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Codelith",
        description="AI-Powered Documentation Generation Platform",
        version="0.1.0",
        debug=settings.APP_DEBUG,
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    register_middleware(app)
    register_exception_handlers(app)

    app.include_router(v1_router, prefix="/api/v1")

    # Published documentation, mounted at the root rather than under /api/v1. The
    # people a site is shared with open it in a browser; they have no account here
    # and no idea what an API is.
    from codelith.apps.documentation.published_api import router as published_router

    app.include_router(published_router)

    @app.get("/health", tags=["Health"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.APP_ENV}

    return app


app = create_app()
