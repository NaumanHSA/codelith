"""
The architecture, as the studio reads it.

`knowledge_bases.architecture_json` is written by a quality-tier call during analysis
and has never been read by anything. It holds the shape of the system: services and
what each one is for, the layers they group into, the relations between them with the
verb that names each one, the patterns the reader recognised, and the stack.

These models exist because that column cannot be trusted as it stands. It is model
output: a key may be missing, a relation may name a service that was never listed, a
layer may hold a module that no longer exists. A component handed the raw JSON would
be one malformed field away from a blank page, so the coercion happens here, once, and
what reaches the studio is always drawable.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ArchService(BaseModel):
    """One component of the system."""

    name: str
    #: `service`, `api`, `worker`, `ui`, `library` — whatever analysis called it.
    #: Free text on purpose: a taxonomy would need updating for every codebase that
    #: does something new, and this is only ever a label on a node.
    type: str = ""
    description: str = ""
    #: Modules that make it up, for the caption and for opening it later.
    modules: list[str] = Field(default_factory=list)


class ArchRelation(BaseModel):
    """An edge, and the verb that names it."""

    source: str
    target: str
    #: `calls`, `configures`, `feeds`, `reads` — the word analysis chose. Drawn on the
    #: edge, because "A relates to B" is not worth a diagram.
    kind: str = ""


class ArchLayer(BaseModel):
    """A named band of modules."""

    name: str
    modules: list[str] = Field(default_factory=list)


class TechStack(BaseModel):
    language: str = ""
    frameworks: list[str] = Field(default_factory=list)
    databases: list[str] = Field(default_factory=list)
    infra: list[str] = Field(default_factory=list)


class ArchitectureOut(BaseModel):
    """
    What the studio draws.

    `available` is the honest answer for a project analysed before this column was
    written, or one where the call produced nothing usable. The page then says so
    rather than rendering an empty diagram and looking broken.
    """

    available: bool = False
    commit_sha: str | None = None
    services: list[ArchService] = Field(default_factory=list)
    relations: list[ArchRelation] = Field(default_factory=list)
    layers: list[ArchLayer] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    tech_stack: TechStack = Field(default_factory=TechStack)
    #: Relations whose endpoints are not among the services. Dropped from the drawing
    #: and counted here, because a diagram with an edge to nowhere is worse than one
    #: that quietly has fewer edges — and silently discarding them would hide a real
    #: analysis defect.
    dangling_relations: int = 0


__all__ = [
    "ArchLayer",
    "ArchRelation",
    "ArchService",
    "ArchitectureOut",
    "TechStack",
]
