"""
Composition workflow — Phase 2.

Writes documents from a knowledge base that already exists. No cloning, no parsing,
no embedding: those were done once during analysis, which is what makes asking for a
second document type cheap.

The back half of the graph (diagram, qa, formatter, publisher) is reused unchanged
from the original documentation pipeline — only the front half needed rebuilding.
"""

from __future__ import annotations

from typing import Any

import structlog
from langgraph.graph import END, StateGraph
from langgraph.types import Send
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.composition import (
    CompositionPlannerAgent,
    CompositionStrategyAgent,
    CompositionWriterAgent,
    KBLoaderAgent,
)
from app.agents.diagram import DiagramAgent
from app.agents.formatter import FormatterAgent
from app.agents.publisher import PublisherAgent
from app.agents.qa import QAAgent
from app.workflows.composition_states import CompositionState

logger = structlog.get_logger(__name__)


class CompositionWorkflow:
    def __init__(self, project, job, db: AsyncSession, sandbox=None) -> None:
        self.project = project
        self.job = job
        self.db = db
        self.job_id = job.id
        self.sandbox = sandbox

    async def run(self) -> dict[str, Any]:
        graph = self._build_graph()
        initial: CompositionState = {
            "project": self.project,
            "job": self.job,
            "job_config": self.job.config_json,
            "sandbox": self.sandbox,
            "generated_docs": [],
        }
        final = await graph.ainvoke(initial)
        return {
            "saved_doc_ids": final.get("saved_doc_ids", []),
            "requires_review": final.get("requires_review", False),
            "kb_id": final.get("kb_id"),
            "error": final.get("error"),
        }

    def _build_graph(self) -> StateGraph:
        job_id = self.job_id

        def make_node(agent_cls):
            async def node(state: CompositionState) -> dict:
                from app.db.session import AsyncSessionLocal
                from app.observability.metrics import time_agent
                from app.observability.tracing import agent_span

                # A session per node so parallel writers never share one.
                async with AsyncSessionLocal() as node_db:
                    agent = agent_cls(db=node_db, job_id=job_id)
                    with time_agent(agent.name), agent_span(agent.name, job_id):
                        return await agent.run(state)

            return node

        graph = StateGraph(CompositionState)

        graph.add_node("kb_loader", make_node(KBLoaderAgent))
        graph.add_node("strategy", make_node(CompositionStrategyAgent))
        graph.add_node("planner", make_node(CompositionPlannerAgent))
        graph.add_node("writer", make_node(CompositionWriterAgent))
        graph.add_node("diagram", make_node(DiagramAgent))
        graph.add_node("qa", make_node(QAAgent))
        graph.add_node("gate", self._gate_node)
        graph.add_node("formatter", make_node(FormatterAgent))
        graph.add_node("publisher", make_node(PublisherAgent))

        graph.set_entry_point("kb_loader")
        # Strategy before planning: audience and depth shape the section plan.
        graph.add_edge("kb_loader", "strategy")
        graph.add_edge("strategy", "planner")

        # One writer per requested document type.
        graph.add_conditional_edges("planner", self._fan_out_writers, ["writer"])

        graph.add_edge("writer", "diagram")
        graph.add_edge("writer", "qa")
        graph.add_edge(["diagram", "qa"], "gate")

        graph.add_conditional_edges(
            "gate",
            self._route_after_review,
            {"format": "formatter", "await_review": END},
        )
        graph.add_edge("formatter", "publisher")
        graph.add_edge("publisher", END)

        return graph.compile()

    @staticmethod
    async def _gate_node(state: CompositionState) -> dict:
        """No-op join for the parallel diagram/qa branches."""
        return {}

    def _fan_out_writers(self, state: CompositionState) -> list[Send]:
        doc_types: list[str] = state.get("doc_types") or ["architecture"]
        # generated_docs is reset per branch: the reducer merges them back on join.
        return [
            Send("writer", {**state, "current_doc_type": dt, "generated_docs": []})
            for dt in doc_types
        ]

    def _route_after_review(self, state: CompositionState) -> str:
        needs_human = state.get("requires_human_review", False)
        all_approved = state.get("all_approved", True)
        human_approved = state.get("human_approved", False)

        if needs_human and not all_approved and not human_approved:
            return "await_review"
        return "format"
