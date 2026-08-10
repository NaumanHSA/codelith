"""Repository for knowledge-base narratives."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from codelith.db.repositories.base import BaseRepository
from codelith.knowledge.constants import NarrativeTopic
from codelith.models.knowledge import KBNarrative


class KBNarrativeRepository(BaseRepository[KBNarrative]):
    model = KBNarrative

    async def upsert(
        self,
        kb_id: int,
        topic: NarrativeTopic | str,
        content_md: str,
        source_refs: dict | None = None,
    ) -> None:
        """One narrative per (kb, topic); re-running a topic replaces it."""
        stmt = insert(KBNarrative).values(
            kb_id=kb_id,
            topic=str(topic),
            content_md=content_md,
            source_refs_json=source_refs or {},
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_kb_narrative_topic",
            set_={
                "content_md": stmt.excluded.content_md,
                "source_refs_json": stmt.excluded.source_refs_json,
            },
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def get(self, kb_id: int, topic: NarrativeTopic | str) -> KBNarrative | None:
        result = await self.session.execute(
            select(KBNarrative).where(
                KBNarrative.kb_id == kb_id, KBNarrative.topic == str(topic)
            )
        )
        return result.scalar_one_or_none()

    async def list_by_kb(self, kb_id: int) -> Sequence[KBNarrative]:
        result = await self.session.execute(
            select(KBNarrative).where(KBNarrative.kb_id == kb_id).order_by(KBNarrative.topic)
        )
        return result.scalars().all()

    async def topics_present(self, kb_id: int) -> set[str]:
        result = await self.session.execute(
            select(KBNarrative.topic).where(KBNarrative.kb_id == kb_id)
        )
        return set(result.scalars().all())


__all__ = ["KBNarrativeRepository"]
