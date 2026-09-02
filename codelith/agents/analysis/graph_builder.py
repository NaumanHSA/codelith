"""
Writing the code graph.

Runs straight after the extractor, because it needs exactly what the extractor
needed — file content and the module roles it just assigned — and nothing that comes
later. Placing it here also means a failure is visible early, before twenty minutes
of summarisation has been spent.

**Non-fatal by design.** Neo4j being unreachable must not fail an analysis. The graph
is an accelerant for questions the documentation pipeline never asks: every consumer
of it today degrades to "no edges" rather than breaking. A knowledge base without a
graph is worth strictly more than no knowledge base, so this agent reports the
failure and lets the run continue.
"""

from __future__ import annotations

from typing import Any

from codelith.agents.base import BaseAgent
from codelith.core.cancellation import JobCancelled
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.knowledge.builder import SourceFile
from codelith.knowledge.graph import build_code_graph
from codelith.memory import get_graph_store
from codelith.memory.graph_store import GraphScope
from codelith.tracing.artifacts import save_artifact


class GraphBuilderAgent(BaseAgent):
    name = "graph_builder_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="GraphBuilder: mapping imports, definitions and calls",
            end_message="GraphBuilder: complete",
        ) as t:
            await self._update_step(self.name, "running")

            project = state["project"]
            kb_id = state.get("kb_id")
            codebase = state.get("codebase")

            files = [
                SourceFile(path=f.path, content=f.content, language=f.language)
                for f in (getattr(codebase, "files", None) or [])
            ]
            if not files or not kb_id:
                await self._emit_log("info", "No parsed files — skipping the code graph")
                await self._update_step(self.name, "completed", {"skipped": True})
                return {"graph_stats": {}}

            # Read back rather than carried through state: the extractor has already
            # persisted these, and threading the whole module list through the graph
            # would put a few hundred rows into every downstream node's state.
            modules = await KnowledgeRepositories.for_session(self.db).modules.list_by_kb(kb_id)
            # Same role vocabulary as `kb_modules`, so a traversal and a KB query
            # describe a module the same way.
            roles = {m.path: m.role for m in modules}

            graph = build_code_graph(files, module_roles=roles)
            save_artifact("graph_builder.counts", graph.counts())

            try:
                async with get_graph_store() as store:
                    stats = await store.write(
                        GraphScope(
                            project_id=project.id,
                            kb_id=kb_id,
                            commit_sha=state.get("commit_sha"),
                        ),
                        graph,
                    )
            except JobCancelled:
                raise
            except Exception as exc:
                # Non-fatal: see the module docstring.
                await self._emit_log("warning", f"Code graph not written: {exc}")
                await self._update_step(self.name, "completed", {"error": str(exc)})
                return {"graph_stats": {}}

            await self._emit_log(
                "info",
                f"Graph: {stats.get('files', 0)} files, {stats.get('imports', 0)} imports, "
                f"{stats.get('calls', 0)} calls",
                **stats,
            )
            t.outputs(**stats)
            await self._update_step(self.name, "completed", stats)
            return {"graph_stats": stats}


__all__ = ["GraphBuilderAgent"]
