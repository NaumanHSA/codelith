"""Repository for the knowledge base root record."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.db.repositories.base import BaseRepository
from app.knowledge.constants import KBStatus
from app.models.knowledge import KnowledgeBase


class KnowledgeBaseRepository(BaseRepository[KnowledgeBase]):
    model = KnowledgeBase

    async def get_with_children(self, kb_id: int) -> KnowledgeBase | None:
        """Load a KB with modules, entities and narratives eagerly attached."""
        result = await self.session.execute(
            select(KnowledgeBase)
            .options(
                selectinload(KnowledgeBase.modules),
                selectinload(KnowledgeBase.entities),
                selectinload(KnowledgeBase.narratives),
            )
            .where(KnowledgeBase.id == kb_id)
        )
        return result.scalar_one_or_none()

    async def get_by_commit(self, project_id: int, commit_sha: str | None) -> KnowledgeBase | None:
        result = await self.session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.project_id == project_id,
                KnowledgeBase.commit_sha.is_(None)
                if commit_sha is None
                else KnowledgeBase.commit_sha == commit_sha,
            )
        )
        return result.scalars().first()

    async def get_latest_usable(self, project_id: int) -> KnowledgeBase | None:
        """
        The KB composition should build from: newest READY or DEGRADED build.

        Returns None when the project has never been analysed, which is the signal
        the API uses to tell the UI to run analysis first.
        """
        result = await self.session.execute(
            select(KnowledgeBase)
            .where(
                KnowledgeBase.project_id == project_id,
                KnowledgeBase.status.in_([KBStatus.READY, KBStatus.DEGRADED]),
            )
            .order_by(KnowledgeBase.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def list_for_project(
        self, project_id: int, limit: int = 20, offset: int = 0
    ) -> Sequence[KnowledgeBase]:
        result = await self.session.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.project_id == project_id)
            .order_by(KnowledgeBase.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def start_build(
        self, project_id: int, commit_sha: str | None, job_id: int | None = None
    ) -> KnowledgeBase:
        """
        Begin (or restart) a build for a project+commit.

        The unique constraint on (project_id, commit_sha) means re-analysing a commit
        reuses its row; children are cleared so a rebuild never mixes generations.
        """
        existing = await self.get_by_commit(project_id, commit_sha)
        if existing is not None:
            await self.clear_children(existing.id)
            existing.status = KBStatus.RUNNING
            existing.job_id = job_id
            existing.error_message = None
            existing.completed_at = None
            existing.stats_json = {}
            await self.session.flush()
            return existing

        return await self.create(
            project_id=project_id,
            commit_sha=commit_sha,
            job_id=job_id,
            status=KBStatus.RUNNING,
        )

    async def clear_children(self, kb_id: int) -> None:
        """Delete modules/entities/narratives/chunks belonging to a KB generation."""
        from sqlalchemy import delete

        from app.models.chunk import CodeChunk
        from app.models.knowledge import KBEntity, KBModule, KBNarrative

        for model in (KBModule, KBEntity, KBNarrative):
            await self.session.execute(delete(model).where(model.kb_id == kb_id))
        await self.session.execute(delete(CodeChunk).where(CodeChunk.kb_id == kb_id))
        await self.session.flush()

    async def finish_build(
        self,
        kb_id: int,
        *,
        status: KBStatus = KBStatus.READY,
        stats: dict | None = None,
        architecture: dict | None = None,
        error: str | None = None,
    ) -> KnowledgeBase | None:
        kb = await self.update(
            kb_id,
            status=status,
            stats_json=stats or {},
            architecture_json=architecture or {},
            error_message=error,
            completed_at=datetime.now(UTC),
        )
        if kb is not None and status.is_usable:
            await self._mark_others_stale(kb.project_id, keep_id=kb_id)
        return kb

    async def _mark_others_stale(self, project_id: int, keep_id: int) -> None:
        """Only one KB per project stays current; older usable builds become STALE."""
        await self.session.execute(
            update(KnowledgeBase)
            .where(
                KnowledgeBase.project_id == project_id,
                KnowledgeBase.id != keep_id,
                KnowledgeBase.status.in_([KBStatus.READY, KBStatus.DEGRADED]),
            )
            .values(status=KBStatus.STALE)
        )
        await self.session.flush()


__all__ = ["KnowledgeBaseRepository"]
