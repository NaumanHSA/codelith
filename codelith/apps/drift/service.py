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
from codelith.services.architecture_service import coerce


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
class ServiceChange:
    """A component that appeared, went, was renamed, or became something else."""

    name: str
    change: str  # added | removed | renamed | retyped
    type_before: str = ""
    type_after: str = ""
    #: Set only on `renamed`, so a reader can see what it used to be called.
    name_before: str = ""


@dataclass(slots=True)
class RelationChange:
    """An edge that appeared, went, or changed its verb."""

    source: str
    target: str
    change: str  # added | removed | reworded
    kind: str = ""
    kind_before: str = ""


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
    services: list[ServiceChange] = field(default_factory=list)
    relations: list[RelationChange] = field(default_factory=list)
    #: False when either reading has no architecture map. Without this, comparing
    #: against a knowledge base written before the column existed reports every
    #: service as newly added, which is a confident description of nothing.
    architecture_comparable: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.modules or self.entities or self.services or self.relations)

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
        # The architecture is the one part that says what the change *means*: a
        # module growing by 200 lines is a fact, a service appearing is a
        # decision somebody made.
        gone = sum(1 for x in self.services if x.change == "removed")
        new = sum(1 for x in self.services if x.change == "added")
        renamed = sum(1 for x in self.services if x.change == "renamed")
        if new:
            bits.append(f"{new} service(s) appeared")
        if gone:
            bits.append(f"{gone} service(s) went")
        # Last, and named for what it is. A rename is the model choosing different
        # words for the same thing, and putting it beside "appeared" and "went" is
        # what made this sentence describe a rewrite that never happened.
        if renamed:
            bits.append(f"{renamed} renamed")
        cut = sum(1 for r in self.relations if r.change == "removed")
        if cut:
            bits.append(f"{cut} connection(s) broke")
        if self.pages_at_risk:
            bits.append(f"**{len(self.pages_at_risk)} written page(s) now describe code that moved**")
        return ", ".join(bits) + "."


#: How much of the smaller service's modules must be shared before two services from
#: different readings are considered the same one under a new name. High enough that
#: two genuinely different components are not merged; low enough to survive a service
#: that gained modules in the same commit that renamed it.
_SAME_SERVICE = 0.6


def _pair_services(left, right):
    """
    Match the services of two readings. Returns `(pairs, only_left, only_right)`.

    Exact names first — when the model happens to agree with itself, that is the
    answer. Everything left over is matched on module membership, best overlap first,
    each service used once. Module names come from the code, so they are the same in
    both readings whatever the model decided to call the thing containing them.

    Greedy rather than optimal: an assignment problem here would be a dozen nodes and
    the difference would never be visible, while the failure mode of greedy — pairing
    a strong match before a slightly stronger one — produces the same set of pairs in
    every case this has been run against.
    """
    by_name = {s.name: s for s in right}
    pairs = [(a, by_name[a.name]) for a in left if a.name in by_name]
    matched_right = {id(b) for _, b in pairs}
    rest_left = [a for a in left if a.name not in by_name]
    rest_right = [b for b in right if id(b) not in matched_right]

    scored = []
    for a in rest_left:
        mods_a = set(a.modules)
        if not mods_a:
            continue
        for b in rest_right:
            mods_b = set(b.modules)
            if not mods_b:
                continue
            shared = len(mods_a & mods_b)
            if not shared:
                continue
            # Against the smaller set, not the union: a service that kept its whole
            # membership and gained five more modules is still that service.
            score = shared / min(len(mods_a), len(mods_b))
            if score >= _SAME_SERVICE:
                scored.append((score, shared, a, b))

    # Strongest first, then by how much evidence backs it, then by name so the result
    # does not depend on dictionary order.
    scored.sort(key=lambda t: (-t[0], -t[1], t[2].name, t[3].name))
    used_left: set[int] = set()
    used_right: set[int] = set()
    for _score, _shared, a, b in scored:
        if id(a) in used_left or id(b) in used_right:
            continue
        used_left.add(id(a))
        used_right.add(id(b))
        pairs.append((a, b))

    only_left = [a for a in rest_left if id(a) not in used_left]
    only_right = [b for b in rest_right if id(b) not in used_right]
    return pairs, only_left, only_right


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
        self._architecture(report, before, after)
        return report

    @staticmethod
    def _architecture(report: DriftReport, before, after) -> None:
        """
        The two maps, compared.

        Two readings and a map per reading have both existed for a while and nothing
        had put them side by side. This is the difference between "these modules
        changed size" and "the thing that talked to the database no longer does".

        Silent unless *both* readings have a map. A knowledge base written before
        `architecture_json` existed, or one whose call produced nothing usable, would
        otherwise make every service look newly added and every edge newly cut. The
        flag says which case a reader is in.
        """
        left = coerce(before.architecture_json or {}, None) if before else None
        right = coerce(after.architecture_json or {}, None) if after else None
        if left is None or right is None or not (left.available and right.available):
            return
        report.architecture_comparable = True

        # Names are the model's words, not the code's, and two readings of an
        # unchanged repository do not agree on them: "HTTP API" one run and
        # "Codelith API" the next. Keyed on name alone, that reported nine services
        # added and eight removed across a diff whose only real change was two new
        # files — a headline that was almost entirely rename noise.
        #
        # So services are paired on the modules they contain, which come from the
        # code. `_pair_services` matches exact names first and falls back to module
        # membership, and what it cannot pair really did appear or go.
        pairs, only_left, only_right = _pair_services(left.services, right.services)

        for a, b in pairs:
            if a.name != b.name:
                report.services.append(
                    ServiceChange(
                        name=b.name, change="renamed", name_before=a.name,
                        type_before=a.type, type_after=b.type,
                    )
                )
            elif a.type != b.type:
                # Worth reporting: an "api" that became a "worker" is a rewrite, not
                # a rename, and the diagram would otherwise look unchanged.
                report.services.append(
                    ServiceChange(
                        name=a.name, change="retyped", type_before=a.type, type_after=b.type
                    )
                )
        for b in only_right:
            report.services.append(
                ServiceChange(name=b.name, change="added", type_after=b.type)
            )
        for a in only_left:
            report.services.append(
                ServiceChange(name=a.name, change="removed", type_before=a.type)
            )
        report.services.sort(key=lambda x: (x.change, x.name))

        # Relations are drawn between service *names*, so an edge whose endpoints were
        # merely renamed would read as one cut and another opened. Rewrite the old
        # map into the new names before comparing, and only genuine edges move.
        renamed = {a.name: b.name for a, b in pairs if a.name != b.name}

        # Keyed on the pair, so a relation whose verb changed reads as one edge
        # reworded rather than as one removed and another added.
        old_edges = {
            (renamed.get(r.source, r.source), renamed.get(r.target, r.target)): r.kind
            for r in left.relations
        }
        new_edges = {(r.source, r.target): r.kind for r in right.relations}
        for pair in sorted(set(old_edges) | set(new_edges)):
            source, target = pair
            if pair not in old_edges:
                report.relations.append(
                    RelationChange(
                        source=source, target=target, change="added", kind=new_edges[pair]
                    )
                )
            elif pair not in new_edges:
                report.relations.append(
                    RelationChange(
                        source=source, target=target, change="removed",
                        kind_before=old_edges[pair],
                    )
                )
            elif old_edges[pair] != new_edges[pair]:
                report.relations.append(
                    RelationChange(
                        source=source, target=target, change="reworded",
                        kind=new_edges[pair], kind_before=old_edges[pair],
                    )
                )

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
