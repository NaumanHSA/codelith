"""
Layering violations, and what is new since the last analysis.

Two questions that look alike and are not:

**"Does this codebase break its own layering?"** An `api` module importing `data_access`
directly has gone round the service layer. That is a static question about one commit.

**"Is that new?"** Two knowledge bases, two graphs, diff the edges. This is the only
thing in Codelith that uses per-commit pinning comparatively — the KB has been keyed by
commit SHA since it was built, and nothing has ever compared two.

**The rules are derived, not imposed.** A layering rule invented in this file would be
an opinion about somebody else's architecture, and the first thing anybody does with an
opinionated linter is turn it off. So the direction of a rule comes from what the
codebase already does: if `api → service` happens two hundred times and `service → api`
twice, the two are the violation. A codebase with no discernible layering produces no
rules, and therefore no findings, which is the right answer for a codebase that has
none.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.memory.graph_store import GraphStore
from codelith.models.knowledge import KnowledgeBase

logger = structlog.get_logger(__name__)

#: How lopsided a pair has to be before the minority direction is called a violation.
#: At 10:1 the rare direction is a mistake; at 3:1 it is a codebase with two
#: conventions, and calling one of them wrong is picking a side nobody asked us to.
_RATIO = 10

#: Below this the sample is too small to mean anything. Two imports one way and none
#: the other is not a convention, it is two imports.
_MIN_EVIDENCE = 8


@dataclass(slots=True)
class DriftFinding:
    source_role: str
    target_role: str
    #: The edges that break the rule, as `from → to` file pairs.
    examples: tuple[tuple[str, str], ...] = ()
    count: int = 0
    #: True when this pair did not exist in the previous knowledge base.
    is_new: bool = False

    @property
    def summary(self) -> str:
        when = "new since the last analysis — " if self.is_new else ""
        return (
            f"{when}{self.count} import{'s' if self.count != 1 else ''} from "
            f"{self.source_role} into {self.target_role}, against the direction the "
            "rest of the codebase uses"
        )


@dataclass(slots=True)
class DriftReport:
    findings: list[DriftFinding] = field(default_factory=list)
    #: The layering the codebase appears to follow, for a reader to sanity-check.
    rules: list[tuple[str, str, int]] = field(default_factory=list)
    compared_with: str | None = None
    #: True when no dominant direction could be found at all.
    no_layering: bool = False

    @property
    def summary(self) -> str:
        if self.no_layering:
            return "No consistent layering was found, so nothing is called a violation."
        if not self.findings:
            return "Every module import follows the direction the codebase uses."
        new = sum(1 for f in self.findings if f.is_new)
        tail = f", {new} new since the last analysis" if new else ""
        return f"{len(self.findings)} layering violation(s){tail}."


class ArchitectureDrift:
    def __init__(self, db: AsyncSession, project_id: int, kb_id: int) -> None:
        self.db = db
        self.project_id = project_id
        self.kb_id = kb_id
        self.repos = KnowledgeRepositories.for_session(db)

    async def run(self) -> DriftReport:
        report = DriftReport()

        roles = await self._roles_by_file()
        if not roles:
            return report

        edges = await self._edges()
        if not edges:
            return report

        pairs = Counter(
            (roles[src], roles[dst])
            for src, dst in edges
            if src in roles and dst in roles and roles[src] != roles[dst]
        )
        rules = _derive_rules(pairs)
        if not rules:
            report.no_layering = True
            return report

        report.rules = [(a, b, pairs[(a, b)]) for a, b in rules]

        previous = await self._previous_pairs()
        for (source, target), count in pairs.items():
            if (target, source) not in rules:
                continue
            examples = tuple(
                (src, dst)
                for src, dst in edges
                if roles.get(src) == source and roles.get(dst) == target
            )[:4]
            report.findings.append(
                DriftFinding(
                    source_role=source,
                    target_role=target,
                    examples=examples,
                    count=count,
                    is_new=previous is not None and (source, target) not in previous,
                )
            )

        report.findings.sort(key=lambda f: (not f.is_new, -f.count))
        logger.info(
            "qa_drift",
            kb_id=self.kb_id,
            rules=len(rules),
            violations=len(report.findings),
            compared=report.compared_with,
        )
        return report

    # ── Inputs ────────────────────────────────────────────────────────────────

    async def _roles_by_file(self) -> dict[str, str]:
        """`path -> role`, from the modules the analysis classified.

        Tests are excluded: a test importing everything is what a test is for, and
        including them makes every layer look violated.
        """
        modules = await self.repos.modules.list_by_kb(self.kb_id, include_tests=False, limit=2000)
        roles: dict[str, str] = {}
        for module in modules:
            role = (module.role or "").strip()
            if not role or role in ("unknown", "test"):
                continue
            for path in module.files_json or []:
                roles[path] = role
        return roles

    async def _edges(self) -> list[tuple[str, str]]:
        """Every internal import, as `(from_file, to_file)`."""
        try:
            async with GraphStore() as graph:
                rows = await graph.query(
                    "MATCH (a:File {project_id: $project_id})-[:IMPORTS]->"
                    "(b:File {project_id: $project_id}) "
                    "RETURN a.path AS src, b.path AS dst",
                    project_id=self.project_id,
                )
        except Exception as exc:
            logger.warning("qa_drift_graph_unavailable", error=str(exc))
            return []
        return [(r["src"], r["dst"]) for r in rows if r.get("src") and r.get("dst")]

    async def _previous_pairs(self) -> set[tuple[str, str]] | None:
        """
        Role pairs from the knowledge base before this one.

        `None` when there is no earlier build — then nothing can be called new, and
        saying "new since the last analysis" about a first run would be a lie about
        history that does not exist.
        """
        previous = (
            await self.db.execute(
                select(KnowledgeBase)
                .where(
                    KnowledgeBase.project_id == self.project_id,
                    KnowledgeBase.id < self.kb_id,
                )
                .order_by(KnowledgeBase.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if previous is None:
            return None

        modules = await self.repos.modules.list_by_kb(previous.id, include_tests=False, limit=2000)
        roles = {
            path: module.role
            for module in modules
            for path in (module.files_json or [])
            if module.role and module.role not in ("unknown", "test")
        }
        # The graph holds only the current build, so the comparison is over the roles
        # each build recorded rather than its edges. Coarser than diffing two graphs,
        # and it is what the stored data supports.
        self_pairs = {
            (roles[src], roles[dst])
            for src, dst in await self._edges()
            if src in roles and dst in roles and roles[src] != roles[dst]
        }
        return self_pairs


def _derive_rules(pairs: Counter) -> set[tuple[str, str]]:
    """
    Which direction each pair of layers is supposed to go.

    A rule is only claimed where the codebase is emphatic: ten times as many imports
    one way as the other, over enough evidence to mean something. Anything less is two
    conventions coexisting, and picking a winner would be an opinion.
    """
    rules: set[tuple[str, str]] = set()
    seen: set[frozenset[str]] = set()

    for source, target in pairs:
        key = frozenset({source, target})
        if key in seen:
            continue
        seen.add(key)

        # Evaluate the *dominant* direction, not whichever the iteration reached
        # first. An earlier version tested whatever came out of the counter, so
        # meeting `service → cli` (1 edge) before `cli → service` (33) discarded the
        # pair — the clearest rule in the codebase was invisible because of dict
        # ordering.
        forward = pairs.get((source, target), 0)
        backward = pairs.get((target, source), 0)
        if backward > forward:
            source, target, forward, backward = target, source, backward, forward

        if forward + backward < _MIN_EVIDENCE:
            continue
        if forward >= max(backward * _RATIO, 1):
            rules.add((source, target))
    return rules


__all__ = ["ArchitectureDrift", "DriftFinding", "DriftReport"]
