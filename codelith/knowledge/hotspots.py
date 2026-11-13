"""
Hotspots: the files where danger collects — changed often, depended on widely, and
reached by no test.

Any one of those alone is ordinary. A file that changes every week is fine if nothing
leans on it; a file half the code imports is fine if it never moves; either is safer
with a test. The three together are where the next regression is most likely to come
from, which is what a lead wants to know first.

The score is `changes × log2(2 + reach) × (1.5 when no test reaches it)`: changes count
fully, because they are what puts a file in play; reach counts with diminishing
returns, so one file imported by everything does not drown the list; a missing test
tips the balance rather than deciding it.

Changes are the last `RECENT_DAYS` days' when the window has enough commits to say
something, and the whole history read otherwise — a codebase that has been quiet for
three months still has files that changed most.

Base, not an app: it reads two things analysis stores (reach, from the graph; churn,
from git) and adds no state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from sqlalchemy.ext.asyncio import AsyncSession

from codelith.knowledge.churn import Churn
from codelith.knowledge.risk import RiskService
from codelith.knowledge.services import SETUP_KINDS
from codelith.models.knowledge import KnowledgeBase

#: Fewer commits than this in the recent window, and the whole history is used.
MIN_RECENT_COMMITS = 5


@dataclass(frozen=True, slots=True)
class Hotspot:
    path: str
    kind: str
    component: str
    #: Commits that touched it in the window used.
    changes: int
    #: Commits that touched it in all the history read.
    changes_total: int
    reach: int
    tests: int
    score: float
    #: `hot` for the top of the list, `warm` for the rest of it.
    level: str


@dataclass(slots=True)
class HotspotReport:
    #: False when the reading has no history: an upload, or a reading taken before
    #: history was kept. `reason` says which.
    available: bool
    reason: str = ""
    #: `recent` (the last `days` days) or `all` (the whole history read).
    window: str = "recent"
    days: int = 0
    commits: int = 0
    recent_commits: int = 0
    since: str | None = None
    shallow: bool = False
    hotspots: list[Hotspot] = field(default_factory=list)


def score(changes: int, reach: int, tested: bool) -> float:
    return round(changes * math.log2(2 + reach) * (1.0 if tested else 1.5), 2)


class HotspotService:
    def __init__(self, db: AsyncSession, kb: KnowledgeBase) -> None:
        self.db = db
        self.kb = kb

    async def rank(self, limit: int = 15, churn: Churn | None = None) -> HotspotReport:
        churn = churn or Churn.from_json(self.kb.churn_json)
        if churn is None:
            return HotspotReport(
                available=False,
                reason="This reading has no change history: it was taken before history was kept, "
                "or its source is not a git repository. Read the codebase again to add it.",
            )
        recent = churn.recent_commits >= MIN_RECENT_COMMITS
        counts = churn.recent if recent else churn.total
        report = HotspotReport(
            available=True,
            window="recent" if recent else "all",
            days=churn.days,
            commits=churn.commits,
            recent_commits=churn.recent_commits,
            since=churn.since,
            shallow=churn.shallow,
        )
        if not counts:
            return report

        ranked, _ = await RiskService(self.db, self.kb).rank(limit=1_000_000)
        found = [
            Hotspot(
                path=r.path,
                kind=r.kind,
                component=r.component,
                changes=counts.get(r.path, 0),
                changes_total=churn.total.get(r.path, 0),
                reach=r.reach,
                tests=r.tests,
                score=score(counts.get(r.path, 0), r.reach, r.tests > 0),
                level="warm",
            )
            for r in ranked
            # A lockfile that changes every week is upkeep, not danger.
            if counts.get(r.path, 0) > 0 and r.kind not in SETUP_KINDS
        ]
        found.sort(key=lambda h: (-h.score, -h.changes, h.path))
        found = found[:limit]
        if found:
            top = found[0].score
            found = [replace(h, level="hot" if h.score >= top * 0.5 else "warm") for h in found]
        report.hotspots = found
        return report


__all__ = ["MIN_RECENT_COMMITS", "Hotspot", "HotspotReport", "HotspotService", "score"]
