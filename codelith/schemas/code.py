"""
The source, as the knowledge base retained it.

Two things shape every type here, and both are consequences of how analysis works
rather than choices this module made.

**The clone is gone.** Analysis discards the checkout when it finishes, so
`code_chunks` is the only copy of any file. What a reader can be shown is exactly
what was indexed, and never more.

**Chunks do not tile a file.** They overlap in places and leave gaps in others.
A file therefore comes back as an ordered list of segments rather than a string,
and a gap is a segment of its own with the line numbers it spans. Splicing the
next chunk onto the last would render code in an order that does not exist in the
file, which is worse than admitting the hole.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FileEntry(BaseModel):
    path: str
    language: str = ""
    #: Lines of code as the parser counted them. Zero when it never parsed the file.
    loc: int = 0
    symbols: int = 0
    #: How many lines of this file the knowledge base actually holds.
    lines_indexed: int = 0
    #: False means analysis saw the file and kept nothing showable of it. The tree
    #: still lists it, because a file silently absent looks like a file that does
    #: not exist.
    has_source: bool = False


class FileTreeOut(BaseModel):
    available: bool = False
    commit_sha: str | None = None
    files: list[FileEntry] = Field(default_factory=list)
    #: Files listed but not readable. Surfaced as a number so the viewer can say so
    #: rather than leaving a reader to notice by clicking.
    without_source: int = 0
    total_loc: int = 0


class CodeSegment(BaseModel):
    """A run of consecutive lines, or a run of consecutive missing ones."""

    kind: Literal["code", "gap"]
    start: int
    end: int
    #: Empty for a gap. There is nothing to show; that is the point of it.
    text: str = ""


class SymbolEntry(BaseModel):
    name: str
    qname: str = ""
    kind: str = ""
    line: int = 0
    end_line: int | None = None
    visibility: str = ""


class FileOut(BaseModel):
    path: str
    language: str = ""
    loc: int = 0
    commit_sha: str | None = None
    segments: list[CodeSegment] = Field(default_factory=list)
    symbols: list[SymbolEntry] = Field(default_factory=list)
    lines_indexed: int = 0
    lines_missing: int = 0
    #: The number of stored chunks this was rebuilt from. Provenance: it says the
    #: page is showing a reconstruction, not a file read off disk.
    chunks: int = 0
    #: False when nothing was retained. The viewer says why instead of showing an
    #: empty pane.
    indexed: bool = True


__all__ = [
    "CodeSegment",
    "FileEntry",
    "FileOut",
    "FileTreeOut",
    "SymbolEntry",
]
