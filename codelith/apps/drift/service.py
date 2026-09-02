"""
What changed between two readings of the same repository, and what it makes wrong.

Every knowledge base is pinned to a commit — `uq_kb_project_commit` has been in the
schema since the beginning and nothing has ever used it for this. Analyse the same
project twice and there are two structured readings of the same code, taken at two
points in time, and the difference between them is a fact nobody has to infer.

**The question this answers is not "what changed in git".** `git diff` already says
that, line by line, and a line-by-line diff of a refactor is noise. This says which
*modules* appeared or grew or vanished, which routes and entrypoints came and went —
and then the part that matters: **which written pages describe code that has since
moved.** A page is not stale because time passed; it is stale because the thing it
describes is different now.

**It reads the knowledge base and nothing else.** No analysis agent knows this app
exists, no new table was added for it, and nothing here re-reads the repository. That
is the whole test of whether an app belongs: if it needed a change to analysis, then
analysis is missing something everyone should have.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.models.knowledge import KBEntity, KBModule, KnowledgeBase
from codelith.models.site import DocPage, DocSite


@dataclass(slots=True)
class ModuleChange:
    """One module, and how it differs between the two readings."""

    path: str
    name: str
    change: str  # added | removed | grew | shrank | rewritten
    loc_before: int = 0
    loc_after: int = 0
    files_before: int = 0
    files_after: int = 0

    @property
    def loc_delta(self) -> int:
        return self.loc_after - self.loc_before


@dataclass(slots=True)
class EntityChange:
    kind: str
    name: str
    change: str  # added | removed
    source_path: str | None = None


@dataclass(slots=True)
class PageAtRisk:
    """A written page whose source has moved under it."""

    address: str
    title: str
    #: The files this page cites that are no longer as they were.
    changed_files: list[str]
    #: What happened to them, in the reader's words rather than the schema's.
    reason: str


@dataclass(slots=True)
class DriftReport:
    project_id: int
    from_commit: str | None
    to_commit: str | None
    modules: list[ModuleChange] = field(default_factory=list)
    entities: list[EntityChange] = field(default_factory=list)
    pages_at_risk: list[PageAtRisk] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.modules or self.entities)

    def summary(self) -> str:
        """One sentence, for a person who will read no further."""
        if self.is_empty:
            return "Nothing structural changed between these two readings."
        added = sum(1 for m in self.modules if m.change == "added")
        removed = sum(1 for m in self.modules if m.change == "removed")
        changed = len(self.modules) - added - removed
        bits = []
        if added:
            bits.append(f"{added} module(s) appeared")
        if removed:
            bits.append(f"{removed} removed")
        if changed:
            bits.append(f"{changed} changed shape")
        if self.pages_at_risk:
            bits.append(f"**{len(self.pages_at_risk)} written page(s) now describe code that moved**")
        return ", ".join(bits) + "."


#: How much a module's size has to move before it is worth mentioning. Below this it
#: is a comment reflowed or an import reordered — true, and not news.
_SIGNIFICANT_LOC = 10


class DriftService:
    """Compares two knowledge bases of one project."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def generations(self, project_id: int) -> list[KnowledgeBase]:
        """Every reading of this project, newest first."""
        rows = await self.db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.project_id == project_id)
            .order_by(KnowledgeBase.id.desc())
        )
        return list(rows.scalars().all())

    async def latest_pair(self, project_id: int) -> tuple[KnowledgeBase, KnowledgeBase] | None:
        """
        The two most recent readings, oldest first.

        `None` when there has only ever been one: drift needs two points, and a
        project analysed once has no history to compare against rather than an empty
        difference.
        """
        gens = await self.generations(project_id)
        if len(gens) < 2:
            return None
        return gens[1], gens[0]

    async def compare(self, project_id: int, before_id: int, after_id: int) -> DriftReport:
        before = await self.db.get(KnowledgeBase, before_id)
        after = await self.db.get(KnowledgeBase, after_id)
        report = DriftReport(
            project_id=project_id,
            from_commit=before.commit_sha if before else None,
            to_commit=after.commit_sha if after else None,
        )

        report.modules = await self._module_changes(before_id, after_id)
        report.entities = await self._entity_changes(before_id, after_id)
        report.pages_at_risk = await self._pages_at_risk(project_id, report.modules)
        return report

    # ── the diffs ─────────────────────────────────────────────────────────────

    async def _modules(self, kb_id: int) -> dict[str, KBModule]:
        rows = await self.db.execute(select(KBModule).where(KBModule.kb_id == kb_id))
        return {m.path: m for m in rows.scalars().all()}

    async def _module_changes(self, before_id: int, after_id: int) -> list[ModuleChange]:
        before = await self._modules(before_id)
        after = await self._modules(after_id)

        out: list[ModuleChange] = []
        for path in sorted(set(before) | set(after)):
            b, a = before.get(path), after.get(path)
            if b is None and a is not None:
                out.append(
                    ModuleChange(path, a.name, "added", 0, a.loc, 0, a.file_count)
                )
            elif a is None and b is not None:
                out.append(
                    ModuleChange(path, b.name, "removed", b.loc, 0, b.file_count, 0)
                )
            elif b is not None and a is not None:
                change = self._how_it_changed(b, a)
                if change:
                    out.append(
                        ModuleChange(
                            path, a.name, change, b.loc, a.loc, b.file_count, a.file_count
                        )
                    )
        return out

    @staticmethod
    def _how_it_changed(before: KBModule, after: KBModule) -> str | None:
        """
        Whether two readings of the same module differ enough to report.

        Symbols first: a module the same size whose symbols have been replaced is the
        interesting case, and the one a size comparison alone would miss entirely.
        """
        b_syms = {s.get("name") if isinstance(s, dict) else s for s in (before.symbols_json or [])}
        a_syms = {s.get("name") if isinstance(s, dict) else s for s in (after.symbols_json or [])}
        if b_syms != a_syms:
            return "rewritten"

        delta = after.loc - before.loc
        if abs(delta) < _SIGNIFICANT_LOC:
            return None
        return "grew" if delta > 0 else "shrank"

    async def _entity_changes(self, before_id: int, after_id: int) -> list[EntityChange]:
        """
        Routes, entrypoints, datastores — the facts a reader is most likely to quote.

        Keyed by `(kind, name)` rather than by id: an entity is the same entity across
        two readings if it is the same kind of thing with the same name, and ids are
        per-generation.
        """

        async def load(kb_id: int) -> dict[tuple[str, str], KBEntity]:
            rows = await self.db.execute(select(KBEntity).where(KBEntity.kb_id == kb_id))
            return {(e.kind, e.name): e for e in rows.scalars().all()}

        before, after = await load(before_id), await load(after_id)
        out: list[EntityChange] = []
        for key in sorted(set(before) - set(after)):
            e = before[key]
            out.append(EntityChange(e.kind, e.name, "removed", e.source_path))
        for key in sorted(set(after) - set(before)):
            e = after[key]
            out.append(EntityChange(e.kind, e.name, "added", e.source_path))
        return out

    async def _pages_at_risk(
        self, project_id: int, modules: list[ModuleChange]
    ) -> list[PageAtRisk]:
        """
        Written pages that cite code which has since changed.

        This is the part worth having. A page records the files it was written from
        (`source_files_json`), so the question is a set intersection rather than a
        guess — no re-reading, no model call, and no "this looks old".

        Only pages with prose: a planned page cannot be wrong about anything yet.
        """
        if not modules:
            return []

        # A module's path is a directory prefix; a page cites files. Matching by
        # prefix is what connects the two without the KB having to store the mapping.
        changed = {m.path: m for m in modules if m.change != "added"}
        if not changed:
            return []

        site = (
            await self.db.execute(select(DocSite).where(DocSite.project_id == project_id))
        ).scalars().first()
        if site is None:
            return []

        rows = await self.db.execute(
            select(DocPage).where(
                DocPage.site_id == site.id,
                DocPage.content_markdown.isnot(None),
                DocPage.version_id.is_(None),  # the live site, not a frozen snapshot
            )
        )

        out: list[PageAtRisk] = []
        for page in rows.scalars().all():
            cited = list(page.source_files_json or [])
            hits: list[str] = []
            reasons: set[str] = set()
            for f in cited:
                for path, change in changed.items():
                    if f == path or f.startswith(path.rstrip("/") + "/"):
                        hits.append(f)
                        reasons.add(change.change)
                        break
            if hits:
                out.append(
                    PageAtRisk(
                        address=f"{page.section_slug}/{page.slug}",
                        title=page.title,
                        changed_files=sorted(set(hits)),
                        reason=_reason_sentence(sorted(reasons)),
                    )
                )
        return out


def _reason_sentence(reasons: list[str]) -> str:
    """The change, in the reader's words rather than the schema's."""
    words = {
        "removed": "code it describes was deleted",
        "rewritten": "the symbols it describes were replaced",
        "grew": "the code it describes has grown",
        "shrank": "the code it describes has shrunk",
    }
    return "; ".join(words.get(r, r) for r in reasons)
