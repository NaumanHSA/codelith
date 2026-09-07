"""
Serving a published site.

Not under `/api/v1`, and deliberately: this is a website. The people it is shared with
open it in a browser, and they do not have an account on this machine, a token in
local storage or any idea what an API is.

**The URL is the authorisation.** A publication's slug ends in 128 bits of
randomness, so holding the link is the whole credential. That is the honest model for
sharing with somebody who cannot sign in, and it is what `rotate` and `unpublish`
exist to revoke. The studio says as much in those words rather than implying more.

**Read-only by construction.** `GET` and `HEAD` are the only methods defined. There is
no write path to secure because there is no write path.

**Nothing half-built is ever reachable.** A publication answers only while its status
is `live` and it points at a build that succeeded. Between a build starting and the
one row update that activates it, this route behaves as though it does not exist.
"""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from codelith.apps.documentation.publishing import paths
from codelith.db.repositories.publication_repo import PublicationRepository
from codelith.dependencies import DbSession
from codelith.models.publication import BuildStatus, PublicationStatus

router = APIRouter(tags=["Published sites"])

#: What a directory request resolves to.
_INDEX = "index.html"


@router.get("/published/{slug}", include_in_schema=False)
async def published_root(slug: str) -> RedirectResponse:
    """
    Send `/published/{slug}` to `/published/{slug}/`.

    Without the trailing slash every relative link on the front page resolves one
    level too high, so the site loads and every link in it is broken. A redirect is
    cheaper than teaching the renderer about two possible base paths.
    """
    return RedirectResponse(url=f"/published/{slug}/", status_code=308)


@router.api_route("/published/{slug}/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def published_file(slug: str, path: str, request: Request, db: DbSession) -> Response:
    """One file out of a published build, or a 404 the reader can understand."""
    publication = await PublicationRepository(db).get_by_slug(slug)

    if (
        publication is None
        or publication.status != PublicationStatus.LIVE
        or publication.current_build is None
        or publication.current_build.status != BuildStatus.SUCCEEDED
    ):
        # One response for "never existed", "taken down" and "still building". A
        # different answer for each would tell somebody who guessed a slug which
        # guesses were close.
        return _gone()

    build = publication.current_build
    root = paths.storage_base() / build.storage_path
    target = paths.resolve_within(root, path or _INDEX)

    if target is None:
        # Escaped the build. Answered as a plain 404: a 403 confirms that something
        # is there to be escaped from.
        return _missing(publication.slug)

    if target.is_dir():
        target = target / _INDEX
    if not target.is_file():
        return _missing(publication.slug)

    # A build directory is immutable, so its id plus the file size identifies this
    # body for as long as it exists. A republish mints a new build id, which
    # invalidates every page of the site at once rather than one at a time.
    etag = f'"{build.id}-{target.stat().st_size}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        target,
        media_type=media_type or "application/octet-stream",
        headers={
            "ETag": etag,
            # Revalidate every time. The bytes are immutable but the *pointer* is
            # not, so a cached page must not outlive the build it came from.
            "Cache-Control": "no-cache",
            # Published docs quote source. Nothing here should end up framed inside
            # somebody else's page, or indexed.
            "X-Frame-Options": "SAMEORIGIN",
            "X-Content-Type-Options": "nosniff",
            "X-Robots-Tag": "noindex, nofollow",
            "Referrer-Policy": "no-referrer",
        },
    )


def _page(title: str, body: str, status: int) -> HTMLResponse:
    """
    A message in the published site's own clothes.

    A reader who followed a link that has been revoked gets a sentence, not a JSON
    error object. They have no studio to go back to and no idea what a 404 body
    normally looks like here.
    """
    return HTMLResponse(
        status_code=status,
        content=(
            "<!doctype html><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{title}</title>"
            "<style>"
            "body{background:#f4f3ef;color:#14120f;margin:0;min-height:100vh;display:flex;"
            "align-items:center;justify-content:center;"
            "font-family:ui-monospace,Menlo,monospace}"
            "main{max-width:44ch;padding:2rem}"
            "h1{font-size:1.1rem;letter-spacing:-.02em;margin:0 0 .75rem}"
            "p{font-size:.85rem;line-height:1.7;color:#55504a;margin:0}"
            "span{color:#c2400c}"
            "</style>"
            f"<main><h1><span>&#9670;</span> {title}</h1><p>{body}</p></main>"
        ),
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )


def _gone() -> HTMLResponse:
    return _page(
        "This documentation is not available",
        "The link may have been withdrawn, or the site may not have finished "
        "building. Ask whoever shared it for a current link.",
        404,
    )


def _missing(slug: str) -> HTMLResponse:
    return _page(
        "Page not found",
        f"That page is not part of this documentation. "
        f"<a style='color:#c2400c' href='/published/{slug}/'>Go to the front page</a>.",
        404,
    )


__all__ = ["router"]
