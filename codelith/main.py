from fastapi import FastAPI
from codelith.config import get_settings
from codelith.core.logging import setup_logging
from codelith.core.middleware import register_middleware
from codelith.core.exceptions import register_exception_handlers
from codelith.core.events import lifespan
from codelith.api.v1.router import v1_router

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

    @app.get("/health", tags=["Health"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.APP_ENV}

    return app


app = create_app()
