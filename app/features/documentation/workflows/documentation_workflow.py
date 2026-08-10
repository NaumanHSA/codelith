from typing import Any

import structlog
from langgraph.graph import END, StateGraph
from langgraph.types import Send
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.architecture import ArchitectureAgent
from app.agents.code_understanding import CodeUnderstandingAgent
from app.agents.coordinator import CoordinatorAgent
from app.features.documentation.agents.diagram import DiagramAgent
from app.features.documentation.agents.formatter import FormatterAgent
from app.agents.planner import PlannerAgent
from app.features.documentation.agents.publisher import PublisherAgent
from app.features.documentation.agents.qa import QAAgent
from app.agents.repo_analyzer import RepoAnalyzerAgent
from app.agents.strategy import StrategyAgent
from app.agents.writer import WriterAgent
from app.features.documentation.workflows.states import DocumentationState

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
        job_id = self.job_id

        def make_node(agent_cls):
            async def node(state: DocumentationState) -> DocumentationState:
                # Each node gets its own session so fan-out writers don't collide
                # during concurrent flush operations on a shared session.
                from app.db.session import AsyncSessionLocal
                from app.observability.metrics import time_agent
                from app.observability.tracing import agent_span
                async with AsyncSessionLocal() as node_db:
                    agent = agent_cls(db=node_db, job_id=job_id)
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

        # ── Post-writing pipeline (diagram and qa run in PARALLEL) ────────────
        graph.add_node("diagram", make_node(DiagramAgent))
        graph.add_node("qa", make_node(QAAgent))
        graph.add_node("gate", self._gate_node)  # no-op join point
        graph.add_node("formatter", make_node(FormatterAgent))
        graph.add_node("publisher", make_node(PublisherAgent))

        # ── Edges ─────────────────────────────────────────────────────────────
        graph.set_entry_point("coordinator")
        graph.add_edge("coordinator", "repo_analyzer")
        graph.add_edge("repo_analyzer", "code_understanding")
        graph.add_edge("code_understanding", "architecture")
        graph.add_edge("architecture", "planner")   # planner now has real data
        graph.add_edge("planner", "strategy")

        # Fan-out: strategy → one writer node per doc_type via Send()
        graph.add_conditional_edges("strategy", self._fan_out_writers, ["writer"])

        # Fan-in: all writers complete (LangGraph waits for all Send()s), then
        # diagram and qa run as PARALLEL branches — they are independent
        # (diagram needs architecture_map + docs; qa needs only docs).
        graph.add_edge("writer", "diagram")
        graph.add_edge("writer", "qa")

        # Join: gate fires only after BOTH diagram and qa have completed
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
    async def _gate_node(state: DocumentationState) -> dict:
        # No-op join point for the parallel diagram/qa branches.
        return {}

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
