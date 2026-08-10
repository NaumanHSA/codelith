"""
What a finding touches — the half no linter can tell you.

Ruff already found the `F821` that broke composition. What it could not say is that the
method runs inside the documentation workflow, so the bug broke *every* documentation
job, and that three written pages cite the file. The finding is a commodity; the reach
is not, and the reach is what the knowledge base already holds.

**Ranking is the product.** A repository returns hundreds of findings and nobody reads
a list of hundreds. Severity alone puts a missing type annotation in a script above an
undefined name in the composition workflow. Severity × reach is what makes the first
ten rows the ten worth reading.

**Degrades, never fails.** Neo4j may be down; a path may not be in the graph; a file
may have arrived after the last analysis. Each of those loses one column, not the
finding — a QA run that reports nothing because the graph was unavailable is worse
than one that reports findings without impact.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.apps.qa.findings import Finding, Impact
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.memory.graph_store import GraphStore
from codelith.models.site import DocPage, DocSite

logger = structlog.get_logger(__name__)

#: Files listed per finding. Enough to make the claim checkable, few enough to read.
_SAMPLE = 4

#: Reach beyond which extra dependents stop changing the decision. A file 200 modules
#: import is not twice as urgent as one 100 import — both mean "this is load-bearing",
#: and without a ceiling the single most-imported file crowds out everything else.
_REACH_CEILING = 40


class ImpactResolver:
    """
    Attaches reach to findings, one repository at a time.

    Built per run and cached per path: a repository yields hundreds of findings across
    dozens of files, and a graph traversal per finding would be hundreds of round trips
    for tens of distinct answers.
    """

    def __init__(self, db: AsyncSession, project_id: int, kb_id: int) -> None:
        self.db = db
        self.project_id = project_id
        self.kb_id = kb_id
        self._reach: dict[str, tuple[int, tuple[str, ...]]] = {}
        self._docs: dict[str, tuple[str, ...]] = {}
        self._symbols: dict[str, list[tuple[int, str]]] = {}
        self._graph_available = True

    async def prepare(self, paths: set[str]) -> None:
        """Load everything the paths need, in as few queries as possible."""
        await self._load_documentation(paths)
        await self._load_symbols(paths)
        await self._load_reach(paths)

    def resolve(self, finding: Finding) -> Finding:
        reached, sample = self._reach.get(finding.path, (0, ()))
        impact = Impact(
            reached_files=reached,
            reached_sample=sample,
            documented_in=self._docs.get(finding.path, ()),
            symbol=self._symbol_at(finding.path, finding.line),
        )
        return finding.with_impact(impact)

    def rank(self, finding: Finding) -> tuple:
        """
        Sort key, worst first.

        Severity dominates — an undefined name is not a style preference — and reach
        breaks ties within a severity. A file nothing imports and no document cites is
        a finding somebody can leave until Friday.
        """
        impact = finding.impact
        reach = min(impact.reached_files, _REACH_CEILING) if impact else 0
        documented = len(impact.documented_in) if impact else 0
        return (
            -finding.severity.rank,
            -(reach + documented * 5),
            finding.path,
            finding.line,
        )

    def explain(self, finding: Finding) -> str:
        """
        One sentence a reader can check, or "" when there is nothing true to say.

        Deliberately not padded. "This affects 0 files" is noise, and a column full of
        it teaches people to skip the column.
        """
        impact = finding.impact
        if impact is None or impact.is_empty:
            return ""

        parts: list[str] = []
        if impact.symbol:
            parts.append(f"in `{impact.symbol}`")
        if impact.reached_files:
            files = "file" if impact.reached_files == 1 else "files"
            parts.append(f"{impact.reached_files} {files} reach it")
        if impact.documented_in:
            pages = "page" if len(impact.documented_in) == 1 else "pages"
            parts.append(f"{len(impact.documented_in)} written {pages} cite it")
        return " · ".join(parts)

    # ── Loading ───────────────────────────────────────────────────────────────

    async def _load_reach(self, paths: set[str]) -> None:
        """
        Who transitively imports each file.

        One traversal per distinct path, not per finding. If the graph is unavailable
        every finding loses this column and keeps the rest — the alternative is a run
        that fails because an optional store is down.
        """
        try:
            async with GraphStore() as graph:
                for path in paths:
                    rows = await graph.get_blast_radius(self.project_id, path)
                    nearest = tuple(
                        r["file"] for r in sorted(rows, key=lambda r: r.get("distance", 99))
                    )[:_SAMPLE]
                    self._reach[path] = (len(rows), nearest)
        except Exception as exc:
            self._graph_available = False
            logger.warning("qa_graph_unavailable", error=str(exc))

    async def _load_documentation(self, paths: set[str]) -> None:
        """Written pages whose provenance names each file.

        Only written ones: a planned page cites nothing yet, and telling somebody a
        page they have not generated is affected is a claim about the future.
        """
        rows = (
            await self.db.execute(
                select(DocPage.title, DocPage.source_files_json)
                .join(DocSite, DocSite.id == DocPage.site_id)
                .where(
                    DocSite.project_id == self.project_id,
                    DocPage.version_id.is_(None),
                    DocPage.status.in_(("ready", "stale")),
                )
            )
        ).all()

        for title, sources in rows:
            for source in sources or []:
                if source in paths:
                    self._docs.setdefault(source, ())
                    self._docs[source] = (*self._docs[source], title)

    async def _load_symbols(self, paths: set[str]) -> None:
        """
        Which symbol each line falls inside — where that can be known.

        **The knowledge base does not record which file a symbol is in.** Symbols are
        stored per *module*, and a module is usually several files, so a symbol at
        line 47 could belong to any of them. Attributing it anyway would put a
        finding inside a function from a different file, which is worse than leaving
        the column empty: a reader cannot tell a confident wrong answer from a right
        one.

        So only single-file modules are attributed. That covers a real share of a
        codebase and is never wrong. Doing better needs per-symbol file attribution,
        which is precisely the kind of thing Q7's deep pass exists to derive rather
        than making every project's analysis carry.

        Within a file, the enclosing symbol is the last one starting at or before the
        line — the KB records where a symbol starts, and `end_line` only sometimes.
        A finding above the first symbol is module-level code and gets nothing.
        """
        repos = KnowledgeRepositories.for_session(self.db)
        modules = await repos.modules.list_by_kb(self.kb_id, include_tests=True, limit=2000)

        for module in modules:
            files = [f for f in (module.files_json or [])]
            if len(files) != 1 or files[0] not in paths:
                continue
            path = files[0]
            for symbol in module.symbols_json or []:
                name = symbol.get("qualified_name") or symbol.get("name")
                line = symbol.get("line")
                if not (name and isinstance(line, int)):
                    continue
                parent = symbol.get("parent")
                self._symbols.setdefault(path, []).append(
                    (line, f"{parent}.{name}" if parent else name)
                )

        for entries in self._symbols.values():
            entries.sort()

    def _symbol_at(self, path: str, line: int) -> str | None:
        entries = self._symbols.get(path)
        if not entries:
            return None
        found: str | None = None
        for start, name in entries:
            if start > line:
                break
            found = name
        return found


__all__ = ["ImpactResolver"]
