"""
Reading the modules analysis wrote.

`kb_modules` holds, per module, a role, a kind, a language, a file list, a symbol
list and a paragraph of prose. The studio has shown a radar of role counts: five
numbers standing in for twenty modules and twenty paragraphs.

The one thing worth stating is that test modules come back. `list_by_kb` defaults to
excluding them because its callers are prompt builders, and a documentation writer
should not spend its context on the test suite. A person browsing a codebase is in
the opposite position: 591 lines of tests across five files is one of the more
useful things on the page, and hiding it would be a claim about the project rather
than a display choice.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from codelith.db.repositories.knowledge.knowledge_base_repo import KnowledgeBaseRepository
from codelith.db.repositories.knowledge.module_repo import KBModuleRepository
from codelith.knowledge.services import assign
from codelith.models.user import User
from codelith.schemas.module import ModuleOut, ModulesOut
from codelith.services.project_service import ProjectService


def _strings(value: object, limit: int = 400) -> list[str]:
    """`files_json` as a list of paths, whatever the column happens to hold."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item][:limit]


def assemble(rows, commit_sha: str | None, architecture: object = None) -> ModulesOut:
    """
    Module rows as the explorer wants them.

    A function rather than a method so the test exercises this and not a copy of it.

    `architecture` is what analysis wrote about this codebase's components. Passing it
    is what lets a module say it belongs to the "Worker Face Tracking Engine" rather
    than only to `service`, which is true of half the repository. Optional, so a
    knowledge base written before the architecture pass existed still assembles.
    """
    grouped = assign(architecture, [row.name for row in rows]) if architecture else {}
    modules = [
        ModuleOut(
            path=row.path,
            name=row.name,
            kind=row.kind or "",
            role=row.role or "",
            service=grouped.get(row.name, ""),
            language=row.language or "",
            file_count=row.file_count or 0,
            loc=row.loc or 0,
            is_test=bool(row.is_test),
            summary=(row.summary or "").strip(),
            files=_strings(row.files_json),
            # The list is stored; only its length is useful at this zoom, and the
            # file viewer already shows the symbols themselves per file.
            symbols=len(row.symbols_json) if isinstance(row.symbols_json, list) else 0,
        )
        for row in rows
    ]
    # Largest first. Size is the closest thing to importance that can be known
    # without reading, and a reader scanning twenty rows starts at the top.
    modules.sort(key=lambda m: (-m.loc, m.name))

    return ModulesOut(
        available=bool(modules),
        commit_sha=commit_sha,
        modules=modules,
        # Test modules are deliberately not summarised, so counting them here would
        # report a gap that is a decision.
        without_summary=sum(1 for m in modules if not m.summary and not m.is_test),
        total_loc=sum(m.loc for m in modules),
    )


class ModuleService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.projects = ProjectService(db)
        self.bases = KnowledgeBaseRepository(db)
        self.modules = KBModuleRepository(db)

    async def list_for_project(self, project_id: int, user: User) -> ModulesOut:
        await self.projects.get(project_id, user)

        kb = await self.bases.get_latest_usable(project_id)
        if kb is None:
            return ModulesOut(available=False)

        rows = await self.modules.list_by_kb(kb.id, include_tests=True)
        return assemble(rows, kb.commit_sha, kb.architecture_json)


__all__ = ["ModuleService", "assemble"]
