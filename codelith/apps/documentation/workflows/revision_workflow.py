"""
Revision workflow — a targeted edit to prose that already exists.

Four nodes, and three of them are borrowed:

    loader → reviser → linker → publisher

`linker` and `publisher` are the composition agents unchanged, because the reviser
emits exactly the shape they already consume. That is deliberate — a revision that
published by its own route would be the second place page provenance is written, and
the two would drift.

**The linker runs over the whole page, not the revised block.** Anchors and
cross-page links are page-wide: a rewritten section can break a `[[page#anchor]]`
link in a section it never touched, and resolving only the new text would not see it.

No planner, no strategy, no QA. The subject is already decided, the audience was
decided when the page was first written, and a revision is reviewed by the person who
asked for it — the diff against `previous_markdown` is right there.
"""

from __future__ import annotations

from typing import Any

import structlog
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.apps.documentation.agents import LinkerAgent
from codelith.apps.documentation.agents.reviser import ReviserAgent
from codelith.apps.documentation.agents.publisher import PublisherAgent
from codelith.apps.documentation.workflows.revision_states import RevisionState

logger = structlog.get_logger(__name__)


class RevisionWorkflow:
    def __init__(self, project, job, db: AsyncSession, sandbox=None) -> None:
        self.project = project
        self.job = job
        self.db = db
        self.job_id = job.id
        self.sandbox = sandbox

    async def run(self, *, page: dict, context: dict) -> dict[str, Any]:
        graph = self._build_graph()
        initial: RevisionState = {
            "project": self.project,
            "job": self.job,
            "job_config": self.job.config_json,
            "sandbox": self.sandbox,
            "page": page,
            "generated_docs": [],
            **context,
        }
        final = await graph.ainvoke(initial)
        return {
            "saved_page_ids": final.get("saved_page_ids", []),
            "kb_id": final.get("kb_id"),
            "new_anchor": final.get("new_anchor"),
            "error": final.get("error"),
        }

    def _build_graph(self):
        graph = StateGraph(RevisionState)

        def make_node(agent_cls):
            async def node(state: RevisionState) -> dict[str, Any]:
                return await agent_cls(db=self.db, job_id=self.job_id).run(state)

            return node

        graph.add_node("reviser", make_node(ReviserAgent))
        graph.add_node("linker", make_node(LinkerAgent))
        graph.add_node("publisher", make_node(PublisherAgent))

        graph.set_entry_point("reviser")
        # A reviser that produced nothing must not reach the publisher: publishing an
        # empty document would blank the page it was asked to improve.
        graph.add_conditional_edges(
            "reviser",
            lambda s: "linker" if s.get("generated_docs") else END,
            ["linker", END],
        )
        graph.add_edge("linker", "publisher")
        graph.add_edge("publisher", END)
        return graph.compile()
