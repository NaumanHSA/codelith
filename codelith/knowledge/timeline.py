"""
The codebase reading after reading: is it getting better or worse?

For each kept reading: how many files and lines each part holds, how many imports run
between parts, and how many of those links run against the columns (a helper importing
the core, the core importing what takes work in) or tie two parts to each other. The
studio draws the trend; the numbers per part show where growth and tangling happen.

A reading never changes once it is finished, so each one's numbers are worked out once
per process and kept (`_cache`). Parts are matched across readings by name, which is
what analysis gives them; a part renamed between two readings shows as one ending and
another beginning, which is what happened as far as the reader can tell.

Base, not an app: it reads the graph and the readings analysis keeps, and stores
nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.knowledge.atlas import UNMAPPED, AtlasService
from codelith.knowledge.constants import KBStatus
from codelith.knowledge.shape import shape_of
from codelith.models.knowledge import KnowledgeBase

#: Readings shown, newest last.
MAX_READINGS = 12


@dataclass(slots=True)
class PartPoint:
    name: str
    files: int
    loc: int
    #: Imports from this part into other parts.
    links_out: int


@dataclass(slots=True)
class Reading:
    kb_id: int
    commit: str | None
    completed_at: str | None
    files: int
    loc: int
    #: Imports between different parts, counted per file pair.
    links: int
    #: Part pairs whose link runs against the columns.
    backwards: list[tuple[str, str]] = field(default_factory=list)
    #: Part pairs that import each other.
    tangled: list[tuple[str, str]] = field(default_factory=list)
    parts: list[PartPoint] = field(default_factory=list)


#: kb id → its numbers. Readings are immutable once finished.
_cache: dict[int, Reading] = {}

_SERVABLE = (KBStatus.READY, KBStatus.STALE, KBStatus.DEGRADED)


class TimelineService:
    def __init__(self, db: AsyncSession, project_id: int) -> None:
        self.db = db
        self.project_id = project_id

    async def readings(self, limit: int = MAX_READINGS) -> list[Reading]:
        rows = (
            await self.db.execute(
                select(KnowledgeBase)
                .where(
                    KnowledgeBase.project_id == self.project_id,
                    KnowledgeBase.status.in_([str(s) for s in _SERVABLE]),
                )
                .order_by(KnowledgeBase.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        out = [await self._reading(kb) for kb in reversed(rows)]
        return out

    async def _reading(self, kb: KnowledgeBase) -> Reading:
        hit = _cache.get(kb.id)
        if hit is not None:
            return hit
        atlas = await AtlasService(self.db, kb).build()
        shape = shape_of(atlas)
        names = [c.name for c in atlas.components]

        files: dict[int, int] = {}
        loc: dict[int, int] = {}
        for n in atlas.nodes:
            if n.fact:
                continue
            files[n.component] = files.get(n.component, 0) + 1
            loc[n.component] = loc.get(n.component, 0) + (n.loc or 0)

        out_links: dict[int, int] = {}
        backwards: list[tuple[str, str]] = []
        tangled: list[tuple[str, str]] = []
        for (a, b), count in shape.links.items():
            out_links[a] = out_links.get(a, 0) + count
            ta, tb = shape.tiers[a], shape.tiers[b]
            if ta >= 0 and tb >= 0 and ta > tb and UNMAPPED not in (names[a], names[b]):
                backwards.append((names[a], names[b]))
            if a < b and (b, a) in shape.links:
                tangled.append((names[a], names[b]))

        reading = Reading(
            kb_id=kb.id,
            commit=kb.commit_sha,
            completed_at=kb.completed_at.isoformat() if kb.completed_at else None,
            files=sum(files.values()),
            loc=sum(loc.values()),
            links=sum(shape.links.values()),
            backwards=sorted(backwards),
            tangled=sorted(tangled),
            parts=sorted(
                (
                    PartPoint(name=names[c], files=files[c], loc=loc.get(c, 0), links_out=out_links.get(c, 0))
                    for c in files
                ),
                key=lambda p: (-p.files, p.name),
            ),
        )
        if kb.completed_at is not None:
            _cache[kb.id] = reading
        return reading


__all__ = ["MAX_READINGS", "PartPoint", "Reading", "TimelineService"]
