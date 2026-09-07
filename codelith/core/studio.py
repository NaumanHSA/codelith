"""
Serving the studio from the API.

In development the studio is a Vite server on :5173 and the API is on :8000, which is
the right arrangement for editing it and the wrong one for running it: two ports, two
processes, and CORS between them. A single container should be one thing you start and
one address you open.

So a built studio, when there is one, is served from the same application as the API.
Nothing about the development setup changes — if `dist/` is not there this does
nothing, and the two-server arrangement carries on.

**Order is the whole design here.** The catch-all that makes client-side routing work
would happily answer `/api/v1/anything`, and an API client asking for a route that does
not exist would get an HTML page and a 200. So the mount happens last, after every real
router, and refuses anything under `/api/` outright rather than relying on registration
order to protect it.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = structlog.get_logger(__name__)

#: Inside the installed package, put there by the image build or by `make studio`.
#: This is what ships in a wheel.
_PACKAGED = Path(__file__).resolve().parent.parent / "studio"

#: A source checkout that has run `pnpm build`. Lets somebody try the production
#: arrangement without installing anything.
_SOURCE = Path(__file__).resolve().parent.parent.parent / "ui" / "dist"


def studio_dir() -> Path | None:
    """Where the built studio is, if it was built."""
    for candidate in (_PACKAGED, _SOURCE):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def mount_studio(app: FastAPI) -> bool:
    """
    Serve the built studio, if there is one. Call this **after** every other router.

    Returns whether anything was mounted, so a caller can say so at startup rather
    than leaving somebody to discover an empty page.
    """
    root = studio_dir()
    if root is None:
        logger.info("studio_not_built", looked_in=[str(_PACKAGED), str(_SOURCE)])
        return False

    assets = root / "assets"
    if assets.is_dir():
        # Hashed filenames, so they are safe to cache hard. Mounted rather than served
        # through the catch-all because StaticFiles handles ranges and conditional
        # requests and the catch-all does not.
        app.mount("/assets", StaticFiles(directory=assets), name="studio-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def studio(path: str) -> FileResponse:
        """
        A file if it exists, otherwise the shell.

        The fallback is what makes `/app/projects/1/code` work on a page refresh:
        the browser asks the server for a route only the browser knows about, and
        the answer is the application that knows what to do with it.
        """
        if path.startswith("api/"):
            # Registration order already protects the real API routes; this protects
            # the *unmatched* ones, which would otherwise get an HTML page and a 200
            # where a client expected a JSON 404.
            raise HTTPException(status_code=404, detail="Not found")

        candidate = (root / path).resolve()
        # A path that escapes the studio directory is not a file we are serving,
        # whatever `..` was used to reach it.
        if path and root in candidate.parents and candidate.is_file():
            return FileResponse(candidate)

        return FileResponse(root / "index.html")

    logger.info("studio_mounted", path=str(root))
    return True


__all__ = ["mount_studio", "studio_dir"]
