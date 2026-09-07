from fastapi import FastAPI

from codelith.api.v1.router import v1_router
from codelith.config import get_settings
from codelith.core.events import lifespan
from codelith.core.exceptions import register_exception_handlers
from codelith.core.logging import setup_logging
from codelith.core.middleware import register_middleware
from codelith.core.runtime import in_container
from codelith.core.studio import mount_studio

setup_logging()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Codelith",
        description="Read a codebase once, then ask it anything.",
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
    async def health() -> dict[str, str | bool]:
        return {
            "status": "ok",
            "env": settings.APP_ENV,
            # The studio needs this and the browser cannot work it out: inside a
            # container `localhost` is the container, so a model endpoint on the
            # host has to be reached at `host.docker.internal`. Knowing that here
            # is what lets the model form say so at the moment it matters.
            "container": in_container(),
        }

    # Last, deliberately. The studio's catch-all answers anything not claimed above
    # it, which is what makes a client-side route survive a page refresh — and which
    # would swallow every API route if it were registered any earlier.
    mount_studio(app)

    return app


app = create_app()
