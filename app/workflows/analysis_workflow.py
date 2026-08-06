"""
Analysis workflow — Phase 1.

Ingests a project and builds its knowledge base. Runs before the user chooses a
document type; the resulting KB is reused by every later composition.

The graph is intentionally linear. The parallelism that matters is *inside*
`module_summarizer` and `narrative_writer`, which fan out over modules and topics
with a bounded semaphore — cheaper than fanning out graph nodes, and it keeps a
single DB session per stage.
"""

from __future__ import annotations

from typing import Any

import structlog
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.analysis import (
    ArchitectureSynthesizerAgent,
    KBPersisterAgent,
    ModuleSummarizerAgent,
    NarrativeWriterAgent,
    SemanticIndexerAgent,
    SitePlannerAgent,
    StructuredExtractorAgent,
)
from app.agents.repo_analyzer import RepoAnalyzerAgent
from app.workflows.analysis_states import AnalysisState

logger = structlog.get_logger(__name__)


class AnalysisWorkflow:
    def __init__(self, project, job, db: AsyncSession, sandbox=None) -> None:
        self.project = project
        self.job = job
        self.db = db
        self.job_id = job.id
        self.sandbox = sandbox

    async def run(self) -> dict[str, Any]:
        graph = self._build_graph()
        initial: AnalysisState = {
            "project": self.project,
            "job": self.job,
            "sandbox": self.sandbox,
        }
        final = await graph.ainvoke(initial)
        return {
            "kb_id": final.get("kb_id"),
            "kb_status": final.get("kb_status"),
            "kb_stats": final.get("kb_stats", {}),
            "error": final.get("error"),
        }

    def _build_graph(self) -> StateGraph:
        job_id = self.job_id

        def make_node(agent_cls):
            async def node(state: AnalysisState) -> dict:
                # Stop between stages: a cancelled job should not start the next agent.
                from app.core.cancellation import check_cancelled

                await check_cancelled()

                # A session per node keeps stages isolated, matching the documentation
                # workflow's convention.
                from app.db.session import AsyncSessionLocal
                from app.observability.metrics import time_agent
                from app.observability.tracing import agent_span

                async with AsyncSessionLocal() as node_db:
                    agent = agent_cls(db=node_db, job_id=job_id)
                    with time_agent(agent.name), agent_span(agent.name, job_id):
                        return await agent.run(state)

            return node

        graph = StateGraph(AnalysisState)

        graph.add_node("repo_analyzer", make_node(RepoAnalyzerAgent))
        graph.add_node("structured_extractor", make_node(StructuredExtractorAgent))
        graph.add_node("semantic_indexer", make_node(SemanticIndexerAgent))
        graph.add_node("module_summarizer", make_node(ModuleSummarizerAgent))
        graph.add_node("architecture_synthesizer", make_node(ArchitectureSynthesizerAgent))
        graph.add_node("narrative_writer", make_node(NarrativeWriterAgent))
        graph.add_node("site_planner", make_node(SitePlannerAgent))
        graph.add_node("kb_persister", make_node(KBPersisterAgent))

        graph.set_entry_point("repo_analyzer")
        graph.add_edge("repo_analyzer", "structured_extractor")
        # Facts first: the extractor opens the KB, so everything downstream has a kb_id.
        graph.add_edge("structured_extractor", "semantic_indexer")
        graph.add_edge("semantic_indexer", "module_summarizer")
        # Synthesis reads the summaries, so it must follow them.
        graph.add_edge("module_summarizer", "architecture_synthesizer")
        graph.add_edge("architecture_synthesizer", "narrative_writer")
        # Last before the seal: planning the site is the one stage that reads
        # everything the others produced — summaries, architecture and narratives —
        # and it is the only stage whose output outlives this knowledge base.
        graph.add_edge("narrative_writer", "site_planner")
        graph.add_edge("site_planner", "kb_persister")
        graph.add_edge("kb_persister", END)

        return graph.compile()
