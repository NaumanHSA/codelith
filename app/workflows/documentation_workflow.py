from typing import Any

import structlog
from langgraph.graph import StateGraph, END
from langgraph.types import Send
from sqlalchemy.ext.asyncio import AsyncSession

from app.workflows.states import DocumentationState
from app.agents.coordinator import CoordinatorAgent
from app.agents.planner import PlannerAgent
from app.agents.repo_analyzer import RepoAnalyzerAgent
from app.agents.code_understanding import CodeUnderstandingAgent
from app.agents.architecture import ArchitectureAgent
from app.agents.strategy import StrategyAgent
from app.agents.writer import WriterAgent
from app.agents.diagram import DiagramAgent
from app.agents.validator import ValidatorAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.formatter import FormatterAgent
from app.agents.publisher import PublisherAgent

logger = structlog.get_logger(__name__)


class DocumentationWorkflow:
    def __init__(self, project, job, db: AsyncSession, sandbox=None) -> None:
        self.project = project
        self.job = job
        self.db = db
        self.job_id = job.id
        self.sandbox = sandbox

    async def run(self) -> dict[str, Any]:
        graph = self._build_graph()
        initial_state: DocumentationState = {
            "project": self.project,
            "job": self.job,
            "job_config": self.job.config_json,
            "generated_docs": [],  # initialise accumulator
            "sandbox": self.sandbox,
        }
        final_state = await graph.ainvoke(initial_state)
        return {
            "saved_doc_ids": final_state.get("saved_doc_ids", []),
            "requires_review": final_state.get("requires_review", False),
            "error": final_state.get("error"),
        }

    def _build_graph(self) -> StateGraph:
        db = self.db
        job_id = self.job_id

        def make_node(agent_cls):
            async def node(state: DocumentationState) -> DocumentationState:
                agent = agent_cls(db=db, job_id=job_id)
                from app.observability.metrics import time_agent
                from app.observability.tracing import agent_span
                with time_agent(agent.name), agent_span(agent.name, job_id):
                    return await agent.run(state)
            return node

        graph = StateGraph(DocumentationState)

        # ── Sequential analysis pipeline ──────────────────────────────────────
        graph.add_node("coordinator", make_node(CoordinatorAgent))
        graph.add_node("planner", make_node(PlannerAgent))
        graph.add_node("repo_analyzer", make_node(RepoAnalyzerAgent))
        graph.add_node("code_understanding", make_node(CodeUnderstandingAgent))
        graph.add_node("architecture", make_node(ArchitectureAgent))
        graph.add_node("strategy", make_node(StrategyAgent))

        # ── Parallel writer fan-out (one Send per doc_type) ──────────────────
        graph.add_node("writer", make_node(WriterAgent))

        # ── Post-writing pipeline ─────────────────────────────────────────────
        graph.add_node("diagram", make_node(DiagramAgent))
        graph.add_node("validator", make_node(ValidatorAgent))
        graph.add_node("reviewer", make_node(ReviewerAgent))
        graph.add_node("formatter", make_node(FormatterAgent))
        graph.add_node("publisher", make_node(PublisherAgent))

        # ── Edges ─────────────────────────────────────────────────────────────
        graph.set_entry_point("coordinator")
        graph.add_edge("coordinator", "planner")
        graph.add_edge("planner", "repo_analyzer")
        graph.add_edge("repo_analyzer", "code_understanding")
        graph.add_edge("code_understanding", "architecture")
        graph.add_edge("architecture", "strategy")

        # Fan-out: strategy → one writer node per doc_type via Send()
        graph.add_conditional_edges("strategy", self._fan_out_writers, ["writer"])

        # Fan-in: all writers → diagram (LangGraph waits for all Send()s)
        graph.add_edge("writer", "diagram")
        graph.add_edge("diagram", "validator")
        graph.add_edge("validator", "reviewer")

        graph.add_conditional_edges(
            "reviewer",
            self._route_after_review,
            {"format": "formatter", "await_review": END},
        )

        graph.add_edge("formatter", "publisher")
        graph.add_edge("publisher", END)

        return graph.compile()

    def _fan_out_writers(self, state: DocumentationState) -> list[Send]:
        doc_types: list[str] = state.get("doc_types", ["architecture"])
        return [
            Send("writer", {**state, "current_doc_type": dt, "generated_docs": []})
            for dt in doc_types
        ]

    def _route_after_review(self, state: DocumentationState) -> str:
        needs_human = state.get("requires_human_review", False)
        all_approved = state.get("all_approved", True)
        human_approved = state.get("human_approved", False)

        if needs_human and not all_approved and not human_approved:
            return "await_review"
        return "format"
