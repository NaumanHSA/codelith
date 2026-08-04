"""Repository for knowledge-base modules."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import Text, cast, func, select
from sqlalchemy.dialects.postgresql import ARRAY, array, insert

from app.db.repositories.base import BaseRepository
from app.knowledge.constants import ModuleRole
from app.models.knowledge import KBModule


class KBModuleRepository(BaseRepository[KBModule]):
    model = KBModule

    async def bulk_upsert(self, kb_id: int, modules: Iterable[dict[str, Any]]) -> int:
        """
        Insert modules in one statement, updating on (kb_id, path) conflict.

        Analysis writes hundreds of these; one round-trip matters.
        """
        rows = [{**m, "kb_id": kb_id} for m in modules]
        if not rows:
            return 0

        stmt = insert(KBModule).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_kb_module_path",
            set_={
                c: stmt.excluded[c]
                for c in (
                    "name", "kind", "role", "language", "file_count", "loc",
                    "is_test", "symbols_json", "files_json", "summary", "updated_at",
                )
                if c in stmt.excluded
            },
        )
        await self.session.execute(stmt)
        await self.session.flush()
        return len(rows)

    async def set_summary(self, kb_id: int, path: str, summary: str) -> None:
        """Written by the module_summarizer agent, one module at a time."""
        await self.session.execute(
            KBModule.__table__.update()
            .where(KBModule.kb_id == kb_id, KBModule.path == path)
            .values(summary=summary)
        )
        await self.session.flush()

    async def list_by_kb(
        self,
        kb_id: int,
        *,
        roles: Sequence[str] | None = None,
        include_tests: bool = False,
        limit: int = 500,
    ) -> Sequence[KBModule]:
        stmt = select(KBModule).where(KBModule.kb_id == kb_id)
        if roles:
            stmt = stmt.where(KBModule.role.in_(list(roles)))
        if not include_tests:
            stmt = stmt.where(KBModule.is_test.is_(False))
        stmt = stmt.order_by(KBModule.loc.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_path(self, kb_id: int, path: str) -> KBModule | None:
        result = await self.session.execute(
            select(KBModule).where(KBModule.kb_id == kb_id, KBModule.path == path)
        )
        return result.scalar_one_or_none()

    async def find_for_files(self, kb_id: int, file_paths: Sequence[str]) -> Sequence[KBModule]:
        """
        Modules covering the given files — the lookup the writer uses to turn a
        section's `key_files` into pre-packed context.
        """
        if not file_paths:
            return []
        result = await self.session.execute(
            select(KBModule).where(
                KBModule.kb_id == kb_id,
                # `?|` ("has any key") requires text[] on the right, not jsonb.
                KBModule.files_json.op("?|")(cast(array(tuple(file_paths)), ARRAY(Text))),
            )
        )
        return result.scalars().all()

    async def role_breakdown(self, kb_id: int) -> dict[str, int]:
        result = await self.session.execute(
            select(KBModule.role, func.count())
            .where(KBModule.kb_id == kb_id)
            .group_by(KBModule.role)
        )
        return {role: count for role, count in result.all()}

    async def count_missing_summaries(self, kb_id: int) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(KBModule)
            .where(
                KBModule.kb_id == kb_id,
                KBModule.summary.is_(None),
                KBModule.is_test.is_(False),
                KBModule.role != ModuleRole.UNKNOWN,
            )
        )
        return int(result.scalar_one())


__all__ = ["KBModuleRepository"]
