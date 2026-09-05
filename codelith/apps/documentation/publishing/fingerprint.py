"""
What makes two publishes the same publish.

A `content_hash` digests everything that can change the built output: the site's
title, the order and titles of its sections, and every page's section, slug, title,
order and markdown. Publishing compares before it builds, so asking to publish a site
that has not moved costs a query rather than a build, and the studio can say so
instead of producing an identical set of files under a new build id.

Two properties matter and both are tested.

**Order stability.** The digest is taken over an explicit sequence, not over a dict
whose iteration order is incidental. Reordering the nav is a real change to the site
and must change the hash; re-reading the same tree must not.

**Renderer identity.** The renderer name and its version are in the digest, because
the same pages through a different renderer, or through a renderer whose output has
changed, is a different site. Without this an upgraded renderer would report the site
as unchanged and go on serving HTML older than the code that renders it.
"""

from __future__ import annotations

import hashlib

from codelith.apps.documentation.formatters.site_tree import SiteTree

#: Written into the digest so a change to *how* the digest is built invalidates every
#: previous one, rather than silently comparing incomparable values.
_SCHEME = "codelith-publish-1"


def content_hash(tree: SiteTree, *, renderer: str, renderer_version: str) -> str:
    """The digest of a site as it would be built, as 64 hex characters."""
    h = hashlib.sha256()

    def feed(*parts: object) -> None:
        # A length-prefixed record per field. Joining on a separator instead would
        # let two different trees collide by moving the separator into a title.
        for part in parts:
            raw = str(part).encode("utf-8")
            h.update(len(raw).to_bytes(4, "big"))
            h.update(raw)

    feed(_SCHEME, renderer, renderer_version)
    feed("title", tree.title)
    feed("version", tree.version_label or "")
    feed("home", tree.home_markdown or "")

    for section in tree.sections:
        feed("section", section.slug, section.title, len(section.pages))
        for page in section.pages:
            feed(
                "page",
                page.section_slug,
                page.slug,
                page.title,
                page.order_index,
                page.content_markdown or "",
            )

    return h.hexdigest()


__all__ = ["content_hash"]
