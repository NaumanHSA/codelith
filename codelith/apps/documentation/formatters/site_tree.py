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

#: The same route, with the link text in front of it, so a link to a page that is not
#: in the export can be unwrapped to plain text instead of left dangling.
_STUDIO_LINK = re.compile(
    r"\[([^\]]*)\]\(/app/projects/\d+/docs/([^)#\s]+)(#[^)\s]*)?\)"
)


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
class SourceSegment:
    """A run of consecutive lines, or a run of consecutive missing ones."""

    kind: str
    start: int
    end: int
    text: str = ""


@dataclass(slots=True)
class SourceFile:
    """
    One file's source, as the knowledge base retained it.

    Carried on the tree so a published site can show the code its pages were
    written from. A page saying "see `src/session/Session.js`" on a site the
    reader cannot leave is a promise with nothing behind it, and it was the
    largest honesty gap between an export and a site somebody trusts.

    `segments` is a list, not a string, for the same reason the studio's viewer
    takes one: the stored chunks do not tile a file, and a gap has to be drawn as
    a gap rather than closed by sliding the next chunk up.
    """

    path: str
    #: Assigned by `SiteTree.attach_sources` so the filename is unique across the
    #: whole site and stable between builds.
    slug: str
    language: str = ""
    segments: list[SourceSegment] = field(default_factory=list)
    lines_indexed: int = 0
    lines_missing: int = 0
    chunks: int = 0


@dataclass(slots=True)
class SiteMeta:
    """
    What the codebase is, as opposed to what was written about it.

    A published site's front page should be able to say more than "here are some
    pages": how big the thing is, what it is written in, where the source lives. All
    of it is already in the knowledge base, and none of it was reaching an export.

    Every field is optional. A project analysed once has all of it; one that has
    never been analysed has none, and the front page simply says less rather than
    printing zeroes.
    """

    repo_url: str | None = None
    commit_sha: str | None = None
    modules: int | None = None
    entities: int | None = None
    files: int | None = None
    languages: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SiteTree:
    """One project's documentation site, as an export target sees it."""

    title: str
    sections: list[ExportSection] = field(default_factory=list)
    home_markdown: str | None = None
    version_label: str | None = None
    meta: SiteMeta = field(default_factory=lambda: SiteMeta())
    #: The code the pages were written from. Empty for a target that does not emit
    #: source, and for a project whose reading kept nothing showable.
    sources: list[SourceFile] = field(default_factory=list)

    @property
    def pages(self) -> list[ExportPage]:
        return [p for s in self.sections for p in s.pages]

    @property
    def is_empty(self) -> bool:
        return not any(s.pages for s in self.sections)

    @property
    def addresses(self) -> set[str]:
        """
        Every page this export actually contains.

        Handed to `rewrite_links` so a link to a page that was planned but never
        written becomes plain text rather than a dead href. Most of a site is usually
        unwritten, so without this an export ships one broken link per unwritten page
        it happens to mention.
        """
        return {p.address for s in self.sections for p in s.pages}

    @property
    def sources_by_path(self) -> dict[str, SourceFile]:
        """The emitted source files, by the path a citation would name."""
        return {f.path: f for f in self.sources}


def rewrite_links(
    markdown: str,
    *,
    from_page: str,
    suffix: str = ".md",
    present: set[str] | None = None,
) -> str:
    """
    Turn studio routes back into relative paths between exported files.

    `from_page` is the address of the page being rewritten, because the result is
    relative to it: a link from `api/endpoints` to `api/schemas` is `schemas.md`,
    but to `guides/setup` it is `../guides/setup.md`. Anchors are preserved.

    `suffix` is `.md` for MkDocs, `.mdx` for Docusaurus, `.html` for the static
    export — the only difference between the three.

    `present` is the set of addresses the export actually contains, and it exists
    because most of a site is usually not written yet. A page in the nav but not yet
    composed is not exported, while the prose of the pages that *were* composed still
    links to it — so without this every export ships dead links, one per unwritten
    page it happened to mention. A real site of two written pages and nineteen planned
    ones produced twenty-two of them, and nobody had noticed, because a downloaded
    archive is not something anyone link-checks.

    A link to a page that is not there becomes its own text. The sentence still reads;
    it just stops promising somewhere to go. Passing `None` keeps every link, which is
    what the studio itself wants, where planned pages are real destinations.
    """
    from_section = from_page.split("/")[0] if "/" in from_page else ""

    def path_to(address: str, anchor: str) -> str:
        section, _, slug = address.partition("/")
        if not slug:
            # A section address with no page — link at the section's index.
            return f"{section}/index{suffix}{anchor}"
        target = f"{slug}{suffix}" if section == from_section else f"../{section}/{slug}{suffix}"
        return f"{target}{anchor}"

    if present is not None:
        def unwrap(match: re.Match[str]) -> str:
            text, address, anchor = match.group(1), match.group(2).rstrip("/"), match.group(3) or ""
            if address not in present:
                return text or address
            return f"[{text}]({path_to(address, anchor)})"

        markdown = _STUDIO_LINK.sub(unwrap, markdown)

    # Whatever is left is a bare route, or every route when `present` is None.
    return _STUDIO_ROUTE.sub(
        lambda m: f"({path_to(m.group(1).rstrip('/'), m.group(2) or '')})", markdown
    )


def slugify_filename(name: str) -> str:
    """A directory or file name safe on every platform we might unzip onto."""
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-") or "page"


__all__ = [
    "ExportPage",
    "SiteMeta",
    "ExportSection",
    "SiteTree",
    "rewrite_links",
    "slugify_filename",
]


#: A fence opening or closing. Citations inside one are code being shown, not code
#: being referred to, and linkifying them would put an anchor inside a `<pre>`.
_FENCE = re.compile(r"^\s*(```|~~~)")

#: An inline code span that is not already the text of a link. The lookarounds are
#: what keep `[`src/x.js`](…)` from being wrapped a second time.
_SPAN = re.compile(r"(?<!\[)`([^`\n]+)`(?!\])")

#: The `:12-30` or `:12` a citation may carry. Split off before the lookup, because
#: the map is keyed on paths and re-attached as the anchor.
_RANGE = re.compile(r"^(.*?):(\d+)(?:-(\d+))?$")


def link_citations(markdown: str, sources: dict[str, SourceFile], prefix: str) -> str:
    """
    Turn every citation naming an emitted file into a link to that file's page.

    **Only exact matches.** A written page's inline code spans are a mixture:
    real paths (`src/util/errors.js`), module names (`src.draw`), types
    (`Image.Image`), and files that exist in the repository but were never indexed
    (`package.json`). Measured across the pages on this machine, fourteen of
    twenty-eight spans on one project resolve and five of ten on the other. Anything
    that does not resolve is left exactly as it is, which is the same rule
    `rewrite_links` follows for pages: a link that goes nowhere is worse than text
    that never promised to.

    A trailing `:12-30` becomes the anchor, so a citation to a range lands on the
    range rather than at the top of the file.
    """
    if not sources:
        return markdown

    out: list[str] = []
    fenced = False
    for line in markdown.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
            out.append(line)
            continue
        out.append(line if fenced else _SPAN.sub(lambda m: _link(m, sources, prefix), line))
    return "\n".join(out)


def _link(match, sources: dict[str, SourceFile], prefix: str) -> str:
    raw = match.group(1).strip()
    path, anchor = raw, ""

    ranged = _RANGE.match(raw)
    if ranged:
        path = ranged.group(1)
        start, end = ranged.group(2), ranged.group(3)
        anchor = f"#L{start}-L{end}" if end else f"#L{start}"

    found = sources.get(path)
    if found is None:
        return match.group(0)
    return f"[`{match.group(1)}`]({prefix}{found.slug}.html{anchor})"


def source_slug(path: str, taken: set[str]) -> str:
    """
    A filename for one source file, unique within the site and stable across builds.

    Sanitising alone collides: `a/b.js` and `a-b.js` both become `a-b-js`. The
    numbered suffix breaks the tie in the caller's iteration order, and the caller
    iterates a sorted list, so the same repository produces the same filenames every
    time. A published site whose URLs move on a rebuild is a site with broken
    bookmarks.
    """
    base = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-") or "file"
    slug, n = base, 1
    while slug in taken:
        n += 1
        slug = f"{base}-{n}"
    taken.add(slug)
    return slug


def cited_paths(markdown: str) -> set[str]:
    """
    Every path a page's prose points at, before knowing which of them exist.

    The counterpart to `link_citations`: that one decides what to link, this one
    decides what to look for. Deliberately loose, because the caller intersects the
    result with what the knowledge base actually holds and a candidate that turns
    out to be a module name or a type simply finds nothing.

    Fenced blocks are skipped for the same reason as in `link_citations`: code being
    shown is not code being referred to, and a sample containing a filename is not a
    citation of it.
    """
    found: set[str] = set()
    fenced = False
    for line in markdown.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        for raw in _SPAN.findall(line):
            text = raw.strip()
            ranged = _RANGE.match(text)
            if ranged:
                text = ranged.group(1)
            # A path has an extension. Without this the set fills with prose - every
            # function name and flag in the page - and every one of them costs a
            # database round trip to discover it is not a file.
            if "." in text.rsplit("/", 1)[-1] and " " not in text:
                found.add(text)
    return found
