"""
Writing a test for something no test names.

**Write only. Nothing is executed.** Running generated code against somebody's
repository needs process isolation, a dependency install, a time limit and a filesystem
boundary — and it is the point at which Codelith stops being read-only about the user's
machine. That is a decision to take deliberately, not to arrive at because generation
felt incomplete without it.

**Aimed at a measured gap.** Q3 says which routes and commands no test names; this
writes for those and nothing else. Generating tests for code that is already tested is
how a tool produces volume instead of value.

**Grounded the same way answers are.** A generated test that imports a module which
does not exist is worse than no test: it fails on the first run and the reader concludes
the feature is broken rather than that the guess was. So every import and symbol the
model produces is checked against the knowledge base, and what does not resolve is
reported — the model proposes, the knowledge base disposes, exactly as citations work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.apps.qa.coverage import SurfaceItem
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.knowledge.retrieval import SectionContextBuilder
from codelith.knowledge.policy import CODE, QUESTION_ANSWERING
from codelith.llm.client import chat_completion
from codelith.llm.router import select_spec

logger = structlog.get_logger(__name__)

#: `from x.y import z` / `import x.y`
_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s|import\s+([\w.]+))", re.M)

#: A fenced block, so a model that explains itself does not put prose in a .py file.
_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)


@dataclass(slots=True)
class GeneratedTest:
    """One test file, and everything needed to judge it before running it."""

    target: str
    suggested_path: str
    code: str
    #: Modules the test imports that the knowledge base knows.
    resolved_imports: tuple[str, ...] = ()
    #: Modules it imports that the knowledge base has never seen. Non-empty means the
    #: test will not run, and saying so beats letting somebody find out.
    unresolved_imports: tuple[str, ...] = ()

    @property
    def grounded(self) -> bool:
        return not self.unresolved_imports

    @property
    def warning(self) -> str:
        if self.grounded:
            return ""
        names = ", ".join(f"`{m}`" for m in self.unresolved_imports)
        return (
            f"This test imports {names}, which the analysis has not seen. Check the "
            "import paths before running it."
        )


@dataclass(slots=True)
class GenerationReport:
    tests: list[GeneratedTest] = field(default_factory=list)
    #: Targets that were asked for and produced nothing usable.
    skipped: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.tests:
            return "Nothing was generated."
        ungrounded = sum(1 for t in self.tests if not t.grounded)
        tail = f", {ungrounded} with imports to check" if ungrounded else ""
        return f"{len(self.tests)} test file(s) written{tail}. None has been run."


class SuiteGenerator:
    def __init__(self, db: AsyncSession, kb_id: int, project_id: int) -> None:
        self.db = db
        self.kb_id = kb_id
        self.project_id = project_id
        self.repos = KnowledgeRepositories.for_session(db)

    async def generate(self, targets: list[SurfaceItem], limit: int = 3) -> GenerationReport:
        """
        Write a test for each target, most valuable first.

        Bounded low on purpose. Three files somebody reads beat twenty they skim, and
        each one is a quality-tier model call against retrieved evidence.
        """
        report = GenerationReport()
        known = await self._known_modules()

        for item in targets[:limit]:
            evidence = await self._evidence(item)
            if not evidence:
                report.skipped.append(item.name)
                continue

            code = await self._write(item, evidence)
            if not code:
                report.skipped.append(item.name)
                continue

            resolved, unresolved = _check_imports(code, known)
            report.tests.append(
                GeneratedTest(
                    target=item.name,
                    suggested_path=_suggest_path(item),
                    code=code,
                    resolved_imports=resolved,
                    unresolved_imports=unresolved,
                )
            )

        logger.info(
            "qa_testgen",
            kb_id=self.kb_id,
            written=len(report.tests),
            skipped=len(report.skipped),
        )
        return report

    async def _known_modules(self) -> set[str]:
        """Dotted module paths the analysis recorded, for checking imports against."""
        modules = await self.repos.modules.list_by_kb(self.kb_id, include_tests=True, limit=2000)
        known: set[str] = set()
        for module in modules:
            if module.name:
                known.add(module.name)
            for path in module.files_json or []:
                known.add(re.sub(r"\.py$", "", path).replace("/", "."))
        return known

    async def _evidence(self, item: SurfaceItem) -> str:
        """The code the test is about — retrieved, not guessed.

        Same shape as the documentation writer: ask the knowledge base for the slice
        that matters, then write from it. A model asked to test a route it has not
        seen invents a handler signature.
        """
        builder = SectionContextBuilder(
            db=self.db,
            kb_id=self.kb_id,
            project_id=self.project_id,
            retrieval_policy=QUESTION_ANSWERING,
        )
        query = f"{item.kind} {item.name} implementation and handler"
        chunks = await builder._search_chunks(query, limit=5, chunk_types=frozenset({CODE}))
        if not chunks:
            return ""
        return "\n\n".join(
            f"--- {c.source_path}:{c.start_line}-{c.end_line} ---\n{c.content}" for c in chunks
        )

    async def _write(self, item: SurfaceItem, evidence: str) -> str:
        system = (
            "You write a single pytest file for one thing in a codebase, using only "
            "the code you are shown.\n\n"
            "Rules:\n"
            "  - Import only modules that appear in the evidence. Never invent a path.\n"
            "  - Test observable behaviour: status codes, return values, raised "
            "errors. Not private helpers.\n"
            "  - If the evidence does not show how to construct something, do not "
            "guess — test what it does show.\n"
            "  - Output one fenced python block and nothing else. No explanation."
        )
        user = (
            f"## The {item.kind} to test\n\n{item.name}"
            + (f"  (declared at {item.where})" if item.where else "")
            + f"\n\n## Code\n\n{evidence}\n"
        )

        try:
            raw = await chat_completion(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                spec=select_spec("write"),
            )
        except Exception as exc:
            logger.warning("qa_testgen_failed", target=item.name, error=str(exc))
            return ""

        return _extract_code(raw)


def _extract_code(raw: str) -> str:
    """The fenced block, or the whole thing if the model forgot the fence.

    A model that explains itself first would otherwise put English at the top of a
    `.py` file, which fails to import before any assertion runs.
    """
    match = _FENCE.search(raw or "")
    body = match.group(1) if match else (raw or "")
    return body.strip()


def _check_imports(code: str, known: set[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """
    Split the test's imports into ones the knowledge base knows and ones it does not.

    Only first-party modules are judged. `pytest`, `httpx` and the standard library are
    not in the knowledge base and never will be, and reporting them as unresolved would
    make every generated test look broken.
    """
    resolved: list[str] = []
    unresolved: list[str] = []

    for match in _IMPORT.finditer(code or ""):
        module = (match.group(1) or match.group(2) or "").strip()
        if not module:
            continue
        root = module.split(".")[0]
        if root not in {m.split(".")[0] for m in known}:
            continue  # third-party or stdlib: not ours to judge
        (resolved if module in known or any(k.startswith(module) for k in known) else unresolved).append(module)

    return tuple(dict.fromkeys(resolved)), tuple(dict.fromkeys(unresolved))


def _suggest_path(item: SurfaceItem) -> str:
    """Where the file would go. A suggestion — nothing is written to disk."""
    slug = re.sub(r"[^a-z0-9]+", "_", item.name.lower()).strip("_") or "surface"
    return f"tests/test_{slug[:40]}.py"


__all__ = ["GeneratedTest", "GenerationReport", "SuiteGenerator"]
