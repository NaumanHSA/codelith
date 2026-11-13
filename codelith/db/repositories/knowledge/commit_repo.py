"""The commits kept per codebase (`SourceCommit`): written as they are read, never twice."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.models.source import SourceCommit


class CommitRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(self, project_id: int, commits: list) -> int:
        """Keep the commits not kept yet. `commits` are `knowledge.history.Commit`s. Returns how many were new."""
        if not commits:
            return 0
        have = set(
            (
                await self.session.execute(
                    select(SourceCommit.sha).where(
                        SourceCommit.project_id == project_id, SourceCommit.sha.in_([c.sha for c in commits])
                    )
                )
            ).scalars()
        )
        new = 0
        for c in commits:
            if c.sha in have:
                continue
            have.add(c.sha)
            self.session.add(
                SourceCommit(
                    project_id=project_id,
                    sha=c.sha,
                    parents_json=list(c.parents),
                    author=c.author[:200],
                    authored_at=c.when,
                    subject=c.subject,
                    files_json=list(c.files),
                )
            )
            new += 1
        await self.session.flush()
        return new

    async def all(self, project_id: int) -> list[SourceCommit]:
        rows = await self.session.execute(select(SourceCommit).where(SourceCommit.project_id == project_id))
        return list(rows.scalars())

    async def count(self, project_id: int) -> int:
        return int(
            (await self.session.execute(select(func.count()).where(SourceCommit.project_id == project_id))).scalar_one()
        )


__all__ = ["CommitRepository"]
