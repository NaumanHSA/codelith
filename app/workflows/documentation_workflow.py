from typing import Any
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from langgraph.graph import StateGraph, END

from app.workflows.states import DocumentationState
from app.agents.coordinator import CoordinatorAgent
from app.agents.planner import PlannerAgent
from app.agents.repo_analyzer import RepoAnalyzerAgent
from app.agents.writer import WriterAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.publisher import PublisherAgent

logger = structlog.get_logger(__name__)


class DocumentationWorkflow:
    def __init__(self, project, job, db: AsyncSession) -> None:
        self.project = project
        self.job = job
        self.db = db
        self.job_id = job.id

    async def run(self) -> dict[str, Any]:
        graph = self._build_graph()
        initial_state: DocumentationState = {
            "project": self.project,
            "job": self.job,
            "job_config": self.job.config_json,
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
                return await agent.run(state)
            return node

        graph = StateGraph(DocumentationState)

        graph.add_node("coordinator", make_node(CoordinatorAgent))
        graph.add_node("planner", make_node(PlannerAgent))
        graph.add_node("repo_analyzer", make_node(RepoAnalyzerAgent))
        graph.add_node("writer", make_node(WriterAgent))
        graph.add_node("reviewer", make_node(ReviewerAgent))
        graph.add_node("publisher", make_node(PublisherAgent))

        graph.set_entry_point("coordinator")
        graph.add_edge("coordinator", "planner")
        graph.add_edge("planner", "repo_analyzer")
        graph.add_edge("repo_analyzer", "writer")
        graph.add_edge("writer", "reviewer")
        graph.add_conditional_edges(
            "reviewer",
            self._route_after_review,
            {"publish": "publisher", "await_review": END},
        )
        graph.add_edge("publisher", END)

        return graph.compile()

    def _route_after_review(self, state: DocumentationState) -> str:
        if state.get("requires_human_review") and not state.get("all_approved"):
            return "await_review"
        return "publish"
