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

from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.knowledge.policy import CODE, QUESTION_ANSWERING
from codelith.knowledge.questions import Evidence
from codelith.knowledge.retrieval import SectionContextBuilder
from codelith.memory import get_graph_store
from codelith.memory.vector_store import VectorStore

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
    {
        "type": "function",
        "function": {
            "name": "trace_flow",
            "description": (
                "How a request travels through the code: from a way in — an API route such "
                "as 'POST /orders', a command, a scheduled job — through each function it "
                "calls, to the code that reads or writes data or calls an outside service. "
                "Reach for it on 'how does X work' and 'what happens when' questions. Give "
                "the route, command or handler name; with no argument it lists the ways in."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entry": {
                        "type": "string",
                        "description": "A route ('POST /orders'), a command name, or a handler or file name.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "how_to",
            "description": (
                "How things of a kind are done in THIS codebase: where they are declared, "
                "where new ones are registered, and an existing one to copy. Call it before "
                "adding a route, a command, a setting, a scheduled job, an event handler, a "
                "model or a test, so the new code follows the house style instead of a "
                "generic one. With `run`: what it needs, and how to install, run and test it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["route", "command", "scheduled_job", "event", "setting", "model", "test", "run"],
                    }
                },
                "required": ["kind"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "qa_findings",
            "description": (
                "What Codelith's QA runs found and nobody has dismissed: security holes, data "
                "leaks, poor error handling, code that will break, dependency problems, failing "
                "tests — each with its exact line, how sure it is and how to fix it. Also says "
                "which areas QA has never checked. Call it when a question is about bugs, risks, "
                "security, vulnerabilities, quality or tests, or before changing a file. Never "
                "say there are no problems in an area it reports as unchecked."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "A file, a folder or a file name. Optional."},
                    "area": {
                        "type": "string",
                        "enum": ["security", "leakage", "dependencies", "errors", "breaks", "performance", "config", "tests"],
                    },
                    "min_severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                },
                "required": [],
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

        async with get_graph_store() as graph:
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

        async with get_graph_store() as graph:
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

        async with get_graph_store() as graph:
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

    async def _trace_flow(self, args: dict) -> tuple[str, list[Evidence]]:
        from codelith.knowledge.flows import FlowService
        from codelith.models.knowledge import KnowledgeBase

        kb = await self.db.get(KnowledgeBase, self.kb_id)
        if kb is None:
            return "This knowledge base no longer exists.", []
        service = FlowService(self.db, kb)
        entry = str(args.get("entry") or "").strip()
        if not entry:
            flows = await service.flows()
            if not flows:
                return (
                    "The analysis found no ways into this code — no routes, commands, "
                    "scheduled jobs or entry points — so there is no request to trace.",
                    [],
                )
            body = "\n".join(
                f"  {f.name}  ({f.label}, {len(f.chain)} step(s)"
                + (f", reaches {f.ends}" if f.ends else "")
                + ")"
                for f in flows[: _LIMIT * 3]
            )
            return f"{len(flows)} way(s) in. Trace one by name:\n{body}", []

        flow = await service.find(entry)
        if flow is None:
            return (
                f"No route, command or entry point matches '{entry}'. Call trace_flow with no "
                "argument to list them.",
                [],
            )
        body = flow.brief()
        evidence = [Evidence(kind="graph", title=f"flow of {flow.name}", body=body, why=f"traced {flow.name}")]
        return body, evidence

    async def _how_to(self, args: dict) -> tuple[str, list[Evidence]]:
        from codelith.knowledge.guide import RECIPE_IDS, GuideService
        from codelith.models.knowledge import KnowledgeBase

        kind = str(args.get("kind") or "").strip()
        if kind not in (*RECIPE_IDS, "run"):
            return f"how_to needs a kind: one of {', '.join((*RECIPE_IDS, 'run'))}.", []
        kb = await self.db.get(KnowledgeBase, self.kb_id)
        if kb is None:
            return "This knowledge base no longer exists.", []
        if kind == "run":
            from codelith.knowledge.runbook import RunbookService

            book = await RunbookService(self.db, kb).build()
            body = book.markdown("How to run it") if book.available else book.reason
            if book.available and book.empty:
                body = "The reading found no manifest, Makefile, compose file or env template saying how to run this."
            return body, [Evidence(kind="graph", title="how to run it", body=body, why="the runbook")]
        recipe = await GuideService(self.db, kb).recipe(kind)
        if recipe is None:
            return (
                f"This codebase has no {kind.replace('_', ' ')}s to learn from — the analysis looked and "
                "found none. Follow the language's usual conventions and keep to the layout of the "
                "nearest similar code.",
                [],
            )
        body = recipe.text()
        return body, [Evidence(kind="graph", title=f"how to: {kind}", body=body, why=f"house style for {kind}")]

    async def _qa_findings(self, args: dict) -> tuple[str, list[Evidence]]:
        from codelith.knowledge.findings import QA_AREAS, SEVERITIES, FindingsReader

        path = str(args.get("path") or "").strip() or None
        area = str(args.get("area") or "").strip() or None
        severity = str(args.get("min_severity") or "").strip() or None
        if area and area not in QA_AREAS:
            return f"area is one of: {', '.join(QA_AREAS)}.", []
        if severity and severity not in SEVERITIES:
            return f"min_severity is one of: {', '.join(SEVERITIES)}.", []
        reader = FindingsReader(self.db, self.project_id)
        coverage = await reader.coverage()
        if not coverage.areas:
            body = (
                "QA has never been run on this codebase, so nothing is known about its security, "
                "bugs, dependencies or tests either way. Running QA (the studio's QA page, or "
                "`codelith qa`) would find out."
            )
            return body, [Evidence(kind="qa", title="QA coverage", body=body, why="no QA run yet")]
        found = await reader.open(path=path, areas=[area] if area else None, min_severity=severity, coverage=coverage)
        head = coverage.brief([area] if area else None)
        lines = ["What QA has checked:", head, ""]
        where = f" in {path}" if path else ""
        if found:
            lines.append(f"{len(found)} open finding(s){where}, most severe first:")
            lines += [k.brief() for k in found[:_LIMIT]]
            if len(found) > _LIMIT:
                lines.append(f"... and {len(found) - _LIMIT} more: narrow by path, area or min_severity.")
        else:
            lines.append(f"No open findings{where} in the areas checked above.")
        evidence = [
            Evidence(kind="qa", title=k.where, body=k.brief() + f"\n{k.message[:500]}", why=f"open QA finding #{k.id}")
            for k in found[:_LIMIT]
        ]
        evidence.append(Evidence(kind="qa", title="QA coverage", body=head, why="which areas QA has checked"))
        return "\n".join(lines), evidence

    @staticmethod
    def _render(evidence: list[Evidence]) -> str:
        return "\n\n".join(f"--- {e.title} ---\n{e.body}" for e in evidence)


__all__ = ["CodebaseTools", "TOOL_SCHEMAS", "TOOL_NAMES"]
