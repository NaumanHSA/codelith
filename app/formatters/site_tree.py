"""
The page tree the export formatters have never had.

MkDocs and Docusaurus are *export targets*: the studio owns the reading experience,
and these produce something a team can host elsewhere. Both formatters existed long
before pages did, so both flattened a project into one file per document type with a
hand-written nav. Given a real tree they can finally emit what they were designed
for — a nested `nav:` and a directory per section.

Two things live here rather than in each formatter, because getting either wrong
breaks every target the same way:

  * **`SiteTree`** — a neutral shape, so a formatter never touches the ORM and can
    be tested with a literal.
  * **`rewrite_links`** — the counterpart to the linker. It resolved cross-page
    references to studio routes because the studio is where pages are read; an
    export has to turn those back into relative file paths. Doing it here is safe
    precisely because the linker already proved every one of those links resolves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: The route shape `LinkerAgent` writes. Captures the page address and any anchor.
_STUDIO_ROUTE = re.compile(r"\(/app/projects/\d+/docs/([^)#\s]+)(#[^)\s]*)?\)")


@dataclass(slots=True)
class ExportPage:
    section_slug: str
    slug: str
    title: str
    content_markdown: str
    order_index: int = 0
    intent: str | None = None
    commit_sha: str | None = None
    source_files: list[str] = field(default_factory=list)

    @property
    def address(self) -> str:
        return f"{self.section_slug}/{self.slug}"


@dataclass(slots=True)
class ExportSection:
    slug: str
    title: str
    pages: list[ExportPage] = field(default_factory=list)


@dataclass(slots=True)
class SiteTree:
    """One project's documentation site, as an export target sees it."""

    title: str
    sections: list[ExportSection] = field(default_factory=list)
    home_markdown: str | None = None
    version_label: str | None = None

    @property
    def pages(self) -> list[ExportPage]:
        return [p for s in self.sections for p in s.pages]

    @property
    def is_empty(self) -> bool:
        return not any(s.pages for s in self.sections)


def rewrite_links(markdown: str, *, from_page: str, suffix: str = ".md") -> str:
    """
    Turn studio routes back into relative paths between exported files.

    `from_page` is the address of the page being rewritten, because the result is
    relative to it: a link from `api/endpoints` to `api/schemas` is `schemas.md`,
    but to `guides/setup` it is `../guides/setup.md`. Anchors are preserved.

    `suffix` is `.md` for MkDocs, `.mdx` for Docusaurus, `.html` for the static
    export — the only difference between the three.
    """
    from_section = from_page.split("/")[0] if "/" in from_page else ""

    def replace(match: re.Match[str]) -> str:
        address = match.group(1).rstrip("/")
        anchor = match.group(2) or ""
        section, _, slug = address.partition("/")
        if not slug:
            # A section address with no page — link at the section's index.
            return f"({section}/index{suffix}{anchor})"
        target = f"{slug}{suffix}" if section == from_section else f"../{section}/{slug}{suffix}"
        return f"({target}{anchor})"

    return _STUDIO_ROUTE.sub(replace, markdown)


def slugify_filename(name: str) -> str:
    """A directory or file name safe on every platform we might unzip onto."""
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-") or "page"


__all__ = [
    "ExportPage",
    "ExportSection",
    "SiteTree",
    "rewrite_links",
    "slugify_filename",
]
