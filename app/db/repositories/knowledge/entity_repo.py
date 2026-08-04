"""Repository for knowledge-base entities (routes, env vars, dependencies, ...)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import func, select

from app.db.repositories.base import BaseRepository
from app.knowledge.constants import EntityKind
from app.models.knowledge import KBEntity


class KBEntityRepository(BaseRepository[KBEntity]):
    model = KBEntity

    async def bulk_add(self, kb_id: int, entities: Iterable[dict[str, Any]]) -> int:
        """
        Insert entities for a KB generation.

        No upsert: `clear_children` wipes the generation before a rebuild, and there
        is no natural unique key (a project can legitimately declare the same route
        name in two places).
        """
        rows = [KBEntity(**{**e, "kb_id": kb_id}) for e in entities]
        if not rows:
            return 0
        self.session.add_all(rows)
        await self.session.flush()
        return len(rows)

    async def list_by_kind(
        self, kb_id: int, kind: EntityKind | str, limit: int = 500
    ) -> Sequence[KBEntity]:
        result = await self.session.execute(
            select(KBEntity)
            .where(KBEntity.kb_id == kb_id, KBEntity.kind == str(kind))
            .order_by(KBEntity.name)
            .limit(limit)
        )
        return result.scalars().all()

    async def kind_breakdown(self, kb_id: int) -> dict[str, int]:
        """
        Counts per entity kind — drives the "suggested document types" the UI shows
        once analysis finishes (routes found → suggest an API reference, and so on).
        """
        result = await self.session.execute(
            select(KBEntity.kind, func.count())
            .where(KBEntity.kb_id == kb_id)
            .group_by(KBEntity.kind)
        )
        return {kind: count for kind, count in result.all()}

    async def search(self, kb_id: int, term: str, limit: int = 50) -> Sequence[KBEntity]:
        result = await self.session.execute(
            select(KBEntity)
            .where(KBEntity.kb_id == kb_id, KBEntity.name.ilike(f"%{term}%"))
            .limit(limit)
        )
        return result.scalars().all()


__all__ = ["KBEntityRepository"]
