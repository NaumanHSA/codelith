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

from codelith.apps.documentation.agents import (
    CompositionPlannerAgent,
    CompositionStrategyAgent,
    CompositionWriterAgent,
    KBLoaderAgent,
    LinkerAgent,
)
from codelith.apps.documentation.agents.diagram import DiagramAgent
from codelith.apps.documentation.agents.formatter import FormatterAgent
from codelith.apps.documentation.agents.publisher import PublisherAgent
from codelith.apps.documentation.agents.qa import QAAgent
from codelith.apps.documentation.workflows.composition_states import CompositionState

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
            "saved_page_ids": final.get("saved_page_ids", []),
            "requires_review": final.get("requires_review", False),
            "kb_id": final.get("kb_id"),
            "error": final.get("error"),
        }

    def _build_graph(self) -> StateGraph:
        job_id = self.job_id

        def make_node(agent_cls):
            async def node(state: CompositionState) -> dict:
                # Stop between stages: a cancelled job should not start the next agent.
                from codelith.core.cancellation import check_cancelled

                await check_cancelled()

                from codelith.db.session import AsyncSessionLocal
                from codelith.observability.metrics import time_agent
                from codelith.observability.tracing import agent_span

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
        graph.add_node("linker", make_node(LinkerAgent))
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

        # Diagram and QA used to run in parallel. Both call the same local model, and
        # LM Studio serving two concurrent requests to one reasoning model returned
        # empty completions for the diagram call — three retries each, twice, on job
        # 10. Sequential costs wall time; concurrent cost every diagram in the
        # document. `gate` stays as the join point.
        # The linker is the join point for the writer fan-out: it is the first
        # node that sees every page of the job at once, which is what resolving a
        # cross-page reference requires.
        graph.add_edge("writer", "linker")
        graph.add_edge("linker", "diagram")
        graph.add_edge("diagram", "qa")
        graph.add_edge("qa", "gate")

        graph.add_node("hold", self._hold_node)

        graph.add_conditional_edges(
            "gate",
            self._route_after_review,
            {"format": "formatter", "await_review": "hold"},
        )
        graph.add_edge("formatter", "publisher")
        graph.add_edge("publisher", END)
        graph.add_edge("hold", END)

        return graph.compile()

    def _build_tail_graph(self):
        """
        The half of the pipeline that runs *after* a person says yes.

        Formatting and publishing are the only stages that had not run when the gate
        held the job, so approval replays exactly those two rather than the whole
        pipeline. Re-running from `kb_loader` would ask the model to write the pages a
        second time, and the text a reviewer approved is not the text they would get.
        """
        job_id = self.job_id

        def make_node(agent_cls):
            async def node(state: CompositionState) -> dict:
                from codelith.core.cancellation import check_cancelled

                await check_cancelled()

                from codelith.db.session import AsyncSessionLocal
                from codelith.observability.metrics import time_agent
                from codelith.observability.tracing import agent_span

                async with AsyncSessionLocal() as node_db:
                    agent = agent_cls(db=node_db, job_id=job_id)
                    with time_agent(agent.name), agent_span(agent.name, job_id):
                        return await agent.run(state)

            return node

        graph = StateGraph(CompositionState)
        graph.add_node("formatter", make_node(FormatterAgent))
        graph.add_node("publisher", make_node(PublisherAgent))
        graph.set_entry_point("formatter")
        graph.add_edge("formatter", "publisher")
        graph.add_edge("publisher", END)
        return graph.compile()

    async def run_tail(self, resumed: dict[str, Any]) -> dict[str, Any]:
        """
        Publish a held job, from the payload stored when it was held.

        `human_approved` is not consulted here — reaching this method *is* the
        approval. The gate is upstream and has already been passed.
        """
        state: CompositionState = {
            **resumed,  # type: ignore[typeddict-item]
            "project": self.project,
            "job": self.job,
            "job_config": self.job.config_json,
            "sandbox": self.sandbox,
            "human_approved": True,
        }
        final = await self._build_tail_graph().ainvoke(state)
        return {
            "saved_doc_ids": final.get("saved_doc_ids", []),
            "saved_page_ids": final.get("saved_page_ids", []),
            "requires_review": False,
            "kb_id": final.get("kb_id"),
            "error": final.get("error"),
        }

    #: State the tail needs and cannot re-derive. Everything absent from this list is
    #: either rebuilt on resume (`project`, `job`, `sandbox`) or was only ever input to
    #: a stage that has already run.
    RESUMABLE_KEYS = (
        "kb_id",
        "kb_status",
        "commit_sha",
        "architecture_map",
        "doc_types",
        "pages",
        "site_map",
        "output_formats",
        "strategy",
        "documentation_plan",
        "generated_docs",
        "linked_docs",
        "link_report",
        "diagrams",
        "validation_results",
        "review_results",
        "all_approved",
    )

    @staticmethod
    async def _gate_node(state: CompositionState) -> dict:
        """No-op join for the parallel diagram/qa branches."""
        return {}

    async def _hold_node(self, state: CompositionState) -> dict:
        """
        Stop, and leave behind enough to start again.

        Everything up to here has run and cost real model time; the pages exist. This
        writes them to the job so that approving publishes *these* pages rather than
        commissioning new ones.
        """
        from codelith.db.session import AsyncSessionLocal
        from codelith.services.job_service import JobService

        payload = {k: state.get(k) for k in self.RESUMABLE_KEYS if state.get(k) is not None}

        async with AsyncSessionLocal() as db:
            await JobService(db).hold_for_review(self.job_id, payload)

        flagged = [
            r for r in (state.get("review_results") or [])
            if not (r.get("review") or {}).get("approved", False)
        ]
        logger.info(
            "composition_held_for_review",
            job_id=self.job_id,
            written=len(state.get("linked_docs") or state.get("generated_docs") or []),
            flagged=len(flagged),
        )
        return {"requires_review": True}

    def _fan_out_writers(self, state: CompositionState) -> list[Send]:
        """
        One writer per unit of work — a page when the job has a page scope, a
        document type otherwise.

        The fan-out is the only place the two modes differ structurally; everything
        downstream of the writer reads `generated_docs` and does not care which
        produced it.
        """
        # generated_docs is reset per branch: the reducer merges them back on join.
        if pages := state.get("pages"):
            return [
                Send("writer", {**state, "current_page": page, "generated_docs": []})
                for page in pages
            ]
        doc_types: list[str] = state.get("doc_types") or ["architecture"]
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
