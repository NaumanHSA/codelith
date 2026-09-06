"""
Narratives, as something a reader can open.

Analysis writes a dozen of these per codebase and they have never been readable in
the product: the studio showed the topic names as chips and dropped the prose. What
a reader wants beside the text is where it came from, so provenance travels with it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class NarrativeProvenance(BaseModel):
    """
    What the writer was looking at when it wrote this.

    Every field can be empty, and for anything analysed before the writer started
    recording it, all of them are. An empty provenance is honest; a fabricated one
    would be worse than none, so nothing here is inferred after the fact.
    """

    generated_by: str = ""
    modules: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)


class NarrativeOut(BaseModel):
    topic: str
    #: The topic as a person would say it, e.g. "Request lifecycle".
    title: str
    #: What this topic is meant to cover. The same line the writer was given.
    brief: str = ""
    content_md: str
    words: int = 0
    provenance: NarrativeProvenance = Field(default_factory=NarrativeProvenance)


class NarrativesOut(BaseModel):
    available: bool = False
    commit_sha: str | None = None
    narratives: list[NarrativeOut] = Field(default_factory=list)


__all__ = ["NarrativeProvenance", "NarrativeOut", "NarrativesOut"]
