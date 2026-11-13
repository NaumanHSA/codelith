"""
Where a codebase is fragile: every file ranked by what an edit to it would touch.

The pre-flight answers this for one target. A person opening a codebase for the first
time wants it for all of them at once — which files are load-bearing, and which of
those nothing tests — and the answer is the same arithmetic run over every file:
transitive reach within three hops, whether a test is among the files reached, and how
many written pages cite it, ranked by `reach_weight`.

No model call, no re-reading: the map the atlas draws (`knowledge/atlas.py`) already
holds every file's kind and every import edge, and the written pages record their
sources. The walk itself is breadth first in memory, which for a few thousand files is
milliseconds and avoids one recursive query per file.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.knowledge.atlas import AtlasService
from codelith.knowledge.preflight import reach_weight, risk_level
from codelith.models.knowledge import KnowledgeBase
from codelith.models.site import DocPage, DocSite

#: The same depth the pre-flight walks, for the same reason.
DEPTH = 3


@dataclass(frozen=True, slots=True)
class FileRisk:
    path: str
    kind: str
    component: str
    direct: int
    reach: int
    tests: int
    pages: int
    weight: int
    level: str


class RiskService:
    def __init__(self, db: AsyncSession, kb: KnowledgeBase) -> None:
        self.db = db
        self.kb = kb

    async def rank(self, limit: int = 15) -> tuple[list[FileRisk], int]:
        """The `limit` riskiest files, and how many files were ranked."""
        atlas = await AtlasService(self.db, self.kb).build()
        nodes = atlas.nodes
        files = [i for i, n in enumerate(nodes) if not n.fact]

        dependants: dict[int, list[int]] = {i: [] for i in files}
        for a, b in atlas.edges:
            if a in dependants and b in dependants:
                dependants[b].append(a)

        pages = await self._pages_by_path()

        ranked: list[FileRisk] = []
        for i in files:
            node = nodes[i]
            if node.kind == "test":
                continue  # a test is what makes others safe, not something at risk
            seen = {i: 0}
            queue = deque([i])
            while queue:
                x = queue.popleft()
                if seen[x] >= DEPTH:
                    continue
                for s in dependants[x]:
                    if s not in seen:
                        seen[s] = seen[x] + 1
                        queue.append(s)
            reached = [j for j in seen if j != i]
            tests = sum(1 for j in reached if nodes[j].kind == "test")
            cited = pages.get(node.path, 0)
            weight = reach_weight(len(reached), cited)
            ranked.append(
                FileRisk(
                    path=node.path,
                    kind=node.kind,
                    component=atlas.components[node.component].name,
                    direct=len(dependants[i]),
                    reach=len(reached),
                    tests=tests,
                    pages=cited,
                    weight=weight,
                    level=risk_level(weight, tests > 0),
                )
            )

        ranked.sort(key=lambda r: (-r.weight, -r.reach, r.path))
        return ranked[:limit], len(ranked)

    async def _pages_by_path(self) -> dict[str, int]:
        """How many written pages of the live site cite each file."""
        rows = (
            await self.db.execute(
                select(DocPage.source_files_json)
                .join(DocSite, DocSite.id == DocPage.site_id)
                .where(
                    DocSite.project_id == self.kb.project_id,
                    DocPage.version_id.is_(None),
                    DocPage.content_markdown.isnot(None),
                )
            )
        ).all()
        out: dict[str, int] = {}
        for (sources,) in rows:
            for path in set(sources or ()):
                out[path] = out.get(path, 0) + 1
        return out


__all__ = ["DEPTH", "FileRisk", "RiskService"]
