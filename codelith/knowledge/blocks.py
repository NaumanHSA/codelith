"""
Addressing one heading inside a page.

A page is stored as a single `content_markdown` blob, but the unit a reader points
at — and asks to have rewritten — is one heading. This module is the only place that
turns the blob into addressable blocks and puts one back.

Three rules it exists to enforce:

* **Fences are not headings.** A page documenting Markdown, or carrying a shell
  snippet full of `#`, splits catastrophically without this. The linker's heading
  scan already knows; so does the studio's `headingsOf`. This is the third copy of
  that rule and they must not drift.
* **A `##` owns its `###`.** Rewriting "Streaming semantics" means rewriting it and
  everything nested beneath it, because that is what a reader sees as the section.
* **Everything outside the block is preserved exactly.** A rewrite touches one
  heading; the rest of the page comes back byte for byte, including whatever
  hand-editing has happened to it.

Blocks are addressed by `anchor_id`, which is already the id the studio stamps on
rendered headings and already the thing the linker validates `#fragment` links
against. Nothing new is invented to name a section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from codelith.knowledge.sites import anchor_id

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE = "```"

#: The level a rewrite addresses. `##` is what the planner decides and what the reader
#: sees as "a section"; `###` are the writer's own sub-structure inside one.
SECTION_LEVEL = 2


@dataclass(frozen=True)
class Block:
    """One heading and everything under it, located in the source."""

    anchor: str
    title: str
    level: int
    #: Line indices into the page, `start` inclusive and `end` exclusive.
    start: int
    end: int
    text: str

    @property
    def body(self) -> str:
        """The prose under the heading, without the heading line itself."""
        return "\n".join(self.text.split("\n")[1:]).strip("\n")


def _heading_lines(markdown: str) -> list[tuple[int, int, str]]:
    """`(line index, level, title)` for every heading outside a fence."""
    out: list[tuple[int, int, str]] = []
    in_fence = False
    for i, line in enumerate(markdown.split("\n")):
        if line.lstrip().startswith(_FENCE):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if match := _HEADING.match(line):
            out.append((i, len(match.group(1)), match.group(2).strip()))
    return out


def split_blocks(markdown: str, level: int = SECTION_LEVEL) -> list[Block]:
    """
    The page's sections at `level`, in document order.

    A block runs from its heading to the next heading of the same level or shallower,
    so a `##` carries its `###` children with it. Anything before the first heading —
    a page's opening paragraph — belongs to no block and is never touched.
    """
    if not markdown:
        return []

    lines = markdown.split("\n")
    headings = _heading_lines(markdown)
    blocks: list[Block] = []

    for position, (line_no, depth, title) in enumerate(headings):
        if depth != level:
            continue
        # Ends at the next heading that is not nested inside this one.
        end = len(lines)
        for next_line, next_depth, _ in headings[position + 1 :]:
            if next_depth <= depth:
                end = next_line
                break
        blocks.append(
            Block(
                anchor=anchor_id(title),
                title=title,
                level=depth,
                start=line_no,
                end=end,
                text="\n".join(lines[line_no:end]).rstrip(),
            )
        )
    return blocks


def find_blocks(markdown: str, anchor: str, level: int = SECTION_LEVEL) -> list[Block]:
    """
    Every block matching an anchor.

    Returns a list rather than one block because two headings on a page can share a
    title, and `anchor_id` maps them to the same id — the studio does not disambiguate
    either. Rewriting whichever came first would silently edit the wrong section, so
    the ambiguity is handed to the caller to refuse.
    """
    return [b for b in split_blocks(markdown, level) if b.anchor == anchor]


def replace_block(markdown: str, block: Block, replacement: str) -> str:
    """
    Put `replacement` where `block` was, leaving the rest of the page untouched.

    The replacement is expected to carry its own heading — that is what the writer
    produces — but one is prepended if it does not, so a model that answered with
    prose alone cannot silently delete the heading and orphan every link to it.

    Its *level* is forced back to the block's. A model asked to rewrite a `##` will
    occasionally answer with `###`, and splicing that verbatim removes the section
    from the page's structure entirely: `split_blocks` no longer sees it, so it
    disappears from the outline, loses its rewrite button, and becomes unreachable
    to every later revision. Only the first heading is adjusted — a replacement that
    legitimately splits into several sections keeps the ones it added.
    """
    # `.strip()`, not `.strip("\n")`: a model answering with spaces and newlines is
    # not answering, and blanking a stored section on that would be silent data loss.
    if not replacement.strip():
        raise ValueError("refusing to replace a section with nothing")
    body = replacement.strip("\n")

    lines = body.split("\n")
    first = lines[0].lstrip()
    if match := _HEADING.match(first):
        if len(match.group(1)) != block.level:
            lines[0] = f"{'#' * block.level} {match.group(2).strip()}"
            body = "\n".join(lines)
    else:
        body = f"{'#' * block.level} {block.title}\n\n{body}"

    lines = markdown.split("\n")
    return "\n".join([*lines[: block.start], *body.split("\n"), *lines[block.end :]])


def block_body(text: str) -> str:
    """
    A revised section with its heading line removed.

    Used when a rename has to be refused but the prose kept — the caller puts the
    original heading back and needs only what came after it.
    """
    lines = text.strip("\n").split("\n")
    if lines and _HEADING.match(lines[0].lstrip()):
        lines = lines[1:]
    return "\n".join(lines).strip("\n")


def word_count(text: str) -> int:
    """
    Prose words, ignoring heading markers.

    `"### A nested heading".split()` counts the `###` as a word, which makes a
    section look longer than it reads. The number is shown to a user deciding whether
    a section is worth rewriting, so it should count what they can see.
    """
    stripped = "\n".join(_HEADING.sub(r"\2", line) for line in text.split("\n"))
    return len(stripped.split())


def outline(markdown: str, level: int = SECTION_LEVEL) -> list[dict]:
    """The page's sections as the studio needs them: what to offer a rewrite of."""
    return [
        {"anchor": b.anchor, "title": b.title, "words": word_count(b.body)}
        for b in split_blocks(markdown, level)
    ]


__all__ = [
    "Block",
    "block_body",
    "SECTION_LEVEL",
    "split_blocks",
    "find_blocks",
    "replace_block",
    "outline",
]
