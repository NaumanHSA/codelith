"""What every check is handed: the reading, its files in scope, and what was asked."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from codelith.core.cancellation import CancellationToken
from codelith.db.repositories.knowledge.source_repo import SourceRepository, StoredFile
from codelith.models.knowledge import KnowledgeBase
from codelith.models.project import ProjectSource


@dataclass(slots=True)
class RunContext:
    db: AsyncSession
    kb: KnowledgeBase
    areas: frozenset[str]
    #: The reading's files the run looks at.
    files: list[StoredFile]
    #: Every file of the reading, for checks that need the neighbours (`.dockerignore`).
    all_files: list[StoredFile]
    sources: list[ProjectSource] = field(default_factory=list)
    token: CancellationToken | None = None
    #: What did not run, or ran partly, in a sentence each; shown with the results.
    notes: list[str] = field(default_factory=list)
    #: Worked out once per run and shared between checks (who can reach what).
    cache: dict = field(default_factory=dict)
    _texts: dict[str, str] = field(default_factory=dict)
    _repo: SourceRepository | None = None

    def wants(self, *areas: str) -> bool:
        return any(a in self.areas for a in areas)

    async def text(self, f: StoredFile) -> str:
        if f.hash not in self._texts:
            repo = self._repo or SourceRepository(self.db)
            self._repo = repo
            self._texts[f.hash] = await repo.text(f.hash) or ""
        return self._texts[f.hash]

    async def lines(self, path: str) -> list[str]:
        f = next((x for x in self.all_files if x.path == path), None)
        return (await self.text(f)).splitlines() if f else []

    async def checkpoint(self) -> None:
        """Stop here if the run was cancelled."""
        if self.token is not None:
            await self.token.raise_if_cancelled()


__all__ = ["RunContext"]
