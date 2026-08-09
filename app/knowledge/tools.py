"""
What a question-answering model may go and look at.

One retrieval pass answers most questions, because the evidence it assembles usually
contains the answer. Measured on the twenty-question set: six answers said the
evidence was insufficient, and two of those six were true absences — the repository
genuinely has no scheduled tasks and no authentication layer. So roughly one question
in five wanted a second look, and this is what it looks with.

**These query the knowledge base, not the filesystem.** Analysis and composition are
separate jobs, and the clone is long gone by the time anybody asks a question. That is
not a limitation to work around: the KB holds the same source, already chunked,
already embedded, plus a graph and a set of facts the filesystem cannot answer from
at all. `find_callers` has no filesystem equivalent short of grepping and guessing.

Every result becomes evidence, so a citation to something a tool fetched resolves
exactly like a citation to something that was pre-loaded. The safety property does not
change; only the size of the pool does.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.policy import CODE, QUESTION_ANSWERING
from app.knowledge.questions import Evidence
from app.knowledge.retrieval import SectionContextBuilder
from app.memory.graph_store import GraphStore
from app.memory.vector_store import VectorStore

logger = structlog.get_logger(__name__)

#: Rows a single tool call may return. A model that asks for "everything" gets a
#: readable slice rather than a context window full of one answer.
_LIMIT = 12

#: The schemas offered to the model. Descriptions are written for the model, not for
#: a developer: each says *when* to reach for it, because a tool a model cannot tell
#: apart from another is a tool it picks at random.
TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": (
                "Search the repository's source for a phrase or an identifier. Use "
                "this when the evidence you were given does not cover something the "
                "question needs, and you can name what is missing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Words the code itself would use, not the asker's words.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a repository file. Use this when evidence names a file that "
                "looks like it holds the answer but you were only shown part of it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repository-relative path."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_callers",
            "description": (
                "Who calls a function or method. Vector search cannot answer this — "
                "nothing in a function's text records who calls it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "A function or method name, e.g. run or Service.fetch.",
                    }
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_dependents",
            "description": "Which files import a given file. Use it to trace who depends on something.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "blast_radius",
            "description": (
                "Everything that transitively imports a file, with distance. Use it "
                "for questions about the impact of changing something."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_facts",
            "description": (
                "Structured facts the analysis extracted. An empty result is a real "
                "answer: it means the repository has none of that kind, which is "
                "worth saying rather than searching for."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "datastore", "external_api", "route", "env_var", "entrypoint",
                            "scheduled_task", "event", "service", "cli_command",
                            "config_file", "infra_resource", "test_suite", "dependency",
                        ],
                    }
                },
                "required": ["kind"],
            },
        },
    },
]

TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOL_SCHEMAS)


class CodebaseTools:
    """Executes what the model asked for, and turns the result into evidence."""

    def __init__(self, db: AsyncSession, kb_id: int, project_id: int) -> None:
        self.db = db
        self.kb_id = kb_id
        self.project_id = project_id
        self.store = VectorStore(db)
        self.repos = KnowledgeRepositories.for_session(db)

    async def run(self, name: str, args: dict) -> tuple[str, list[Evidence]]:
        """
        `(what the model sees, what the citation checker sees)`.

        Both, because they are different things. The model needs prose it can read;
        the checker needs the paths that were actually fetched, so a citation to one
        of them resolves.

        Never raises. A tool that fails returns a sentence saying so — the model can
        try something else, where an exception ends the answer.
        """
        try:
            handler = getattr(self, f"_{name}", None)
            if handler is None:
                return f"No such tool: {name}.", []
            return await handler(args)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("tool_failed", tool=name, error=str(exc))
            return f"That lookup failed: {exc}", []

    # ── Tools ─────────────────────────────────────────────────────────────────

    async def _search_code(self, args: dict) -> tuple[str, list[Evidence]]:
        query = str(args.get("query") or "").strip()
        if not query:
            return "search_code needs a query.", []

        builder = SectionContextBuilder(
            db=self.db, kb_id=self.kb_id, project_id=self.project_id,
            retrieval_policy=QUESTION_ANSWERING,
        )
        chunks = await builder._search_chunks(query, limit=6, chunk_types=frozenset({CODE}))
        if not chunks:
            return f"Nothing in the source matched '{query}'.", []

        evidence = [
            Evidence(
                kind="code",
                title=f"{c.source_path}:{c.start_line}-{c.end_line}",
                body=c.content,
                why=f"searched for '{query}'",
            )
            for c in chunks
        ]
        return self._render(evidence), evidence

    async def _read_file(self, args: dict) -> tuple[str, list[Evidence]]:
        path = str(args.get("path") or "").strip()
        if not path:
            return "read_file needs a path.", []

        chunks = await self.store.get_by_paths(self.kb_id, [path])
        if not chunks:
            return (
                f"'{path}' is not in this knowledge base. It may not exist, or may "
                "have been excluded from analysis.",
                [],
            )

        evidence = [
            Evidence(
                kind="code",
                title=f"{c.source_path}:{c.start_line}-{c.end_line}",
                body=c.content,
                why=f"read {path}",
            )
            for c in sorted(chunks, key=lambda c: c.start_line or 0)[:_LIMIT]
        ]
        return self._render(evidence), evidence

    async def _find_callers(self, args: dict) -> tuple[str, list[Evidence]]:
        symbol = str(args.get("symbol") or "").strip().split(".")[-1]
        if not symbol:
            return "find_callers needs a symbol.", []

        async with GraphStore() as graph:
            rows = await graph.get_callers(self.project_id, symbol)
        if not rows:
            return (
                f"Nothing recorded calls '{symbol}'. Call edges are resolved only "
                "where the callee is unambiguous, so this is not proof of no callers.",
                [],
            )

        body = "\n".join(f"  {r['file']} :: {r['caller']}" for r in rows[:_LIMIT])
        evidence = [Evidence(
            kind="graph", title=f"callers of {symbol}", body=body,
            why=f"traced callers of {symbol}",
        )]
        return f"{len(rows)} caller(s) of {symbol}:\n{body}", evidence

    async def _find_dependents(self, args: dict) -> tuple[str, list[Evidence]]:
        path = str(args.get("path") or "").strip()
        if not path:
            return "find_dependents needs a path.", []

        async with GraphStore() as graph:
            files = await graph.get_dependents(self.project_id, path)
        if not files:
            return f"Nothing imports '{path}'.", []

        body = "\n".join(f"  {f}" for f in files[:_LIMIT])
        evidence = [Evidence(
            kind="graph", title=f"importers of {path}", body=body,
            why=f"traced what imports {path}",
        )]
        return f"{len(files)} file(s) import {path}:\n{body}", evidence

    async def _blast_radius(self, args: dict) -> tuple[str, list[Evidence]]:
        path = str(args.get("path") or "").strip()
        if not path:
            return "blast_radius needs a path.", []

        async with GraphStore() as graph:
            rows = await graph.get_blast_radius(self.project_id, path)
        if not rows:
            return f"Nothing depends on '{path}', directly or transitively.", []

        body = "\n".join(f"  {r['distance']} hop(s): {r['file']}" for r in rows[:_LIMIT])
        evidence = [Evidence(
            kind="graph", title=f"impact of {path}", body=body,
            why=f"traced the blast radius of {path}",
        )]
        return f"{len(rows)} file(s) reach {path}:\n{body}", evidence

    async def _list_facts(self, args: dict) -> tuple[str, list[Evidence]]:
        kind = str(args.get("kind") or "").strip()
        if not kind:
            return "list_facts needs a kind.", []

        rows = await self.repos.entities.list_by_kind(self.kb_id, kind, limit=_LIMIT * 2)
        if not rows:
            # A real answer, and one worth being definite about: the analysis looked
            # for these and found none.
            return (
                f"The analysis found no {kind} in this repository. That is a finding, "
                "not a gap — it looked and there are none.",
                [],
            )

        body = "\n".join(
            f"  {r.name}" + (f"  ({r.source_path}:{r.source_line})" if r.source_path else "")
            for r in rows
        )
        evidence = [Evidence(
            kind="entity", title=f"{kind} facts", body=body, why=f"listed {kind} entities",
        )]
        return f"{len(rows)} {kind}:\n{body}", evidence

    @staticmethod
    def _render(evidence: list[Evidence]) -> str:
        return "\n\n".join(f"--- {e.title} ---\n{e.body}" for e in evidence)


__all__ = ["CodebaseTools", "TOOL_SCHEMAS", "TOOL_NAMES"]
