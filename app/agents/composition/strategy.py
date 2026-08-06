"""
Documentation strategy, read from the knowledge base.

Decides audience, tone and whether diagrams are worth the cost. Unlike the previous
strategy agent this reads the analysis narratives rather than re-deriving a picture of
the codebase from a file listing.
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.base import BaseAgent
from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.constants import NarrativeTopic
from app.knowledge.narratives import topics_for_doc_type
from app.llm.prompts.composition_prompts import COMPOSITION_STRATEGY
from app.tracing.artifacts import save_artifact, save_input_artifact


class CompositionStrategyAgent(BaseAgent):
    name = "composition_strategy_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="Strategy: choosing audience and depth",
            end_message="Strategy: complete",
        ) as t:
            await self._update_step(self.name, "running")

            project = state["project"]
            kb_id = state["kb_id"]
            doc_types: list[str] = state.get("doc_types") or ["architecture"]
            stats: dict = state.get("kb_stats") or {}
            repos = KnowledgeRepositories.for_session(self.db)

            # Narratives for what was actually requested. Hardcoding overview +
            # architecture meant an API document's strategy call never saw an endpoint:
            # the routes were in the request_lifecycle narrative, which was not passed.
            overview = await repos.narratives.get(kb_id, NarrativeTopic.OVERVIEW)
            relevant = await self._narratives(repos, kb_id, doc_types)

            messages = COMPOSITION_STRATEGY.render(
                project_name=project.name,
                doc_types=", ".join(doc_types),
                overview=(overview.content_md if overview else "(none)"),
                architecture=relevant or "(none)",
                roles=json.dumps(stats.get("roles", {})),
                facts=json.dumps(stats.get("entity_kinds", {})),
            )

            save_input_artifact("strategy.prompt", messages)

            strategy = await self._call_llm_json(messages, task_type="plan")
            if not strategy or not isinstance(strategy, dict):
                strategy = self._default(doc_types, stats)
                await self._emit_log("warning", "Strategy fell back to defaults")

            strategy.setdefault("audiences", self._default(doc_types, stats)["audiences"])
            strategy.setdefault("generate_diagrams", True)

            save_artifact("strategy.strategy", strategy)

            t.outputs(doc_types=doc_types, diagrams=strategy.get("generate_diagrams"))
            await self._update_step(self.name, "completed", {"doc_types": doc_types})
            return {"strategy": strategy}

    @staticmethod
    async def _narratives(repos, kb_id: int, doc_types: list[str]) -> str:
        """
        Every narrative the requested document types read, at full length.

        This is one call per composition job. All narratives together are roughly
        4,600 tokens, so the old flat 1,500-character cut — which discarded 71% of the
        architecture narrative mid-word — bought nothing.
        """
        wanted: list[NarrativeTopic] = []
        for doc_type in doc_types:
            for topic in topics_for_doc_type(doc_type):
                if topic not in wanted:
                    wanted.append(topic)

        blocks: list[str] = []
        for topic in wanted:
            if narrative := await repos.narratives.get(kb_id, topic):
                blocks.append(f"### {topic}\n{narrative.content_md}")
        return "\n\n".join(blocks)

    @staticmethod
    def _default(doc_types: list[str], stats: dict) -> dict:
        roles = stats.get("roles", {})
        # Diagrams only pay off when there is real structure to draw.
        worth_drawing = len(roles) >= 3 or stats.get("entity_kinds", {}).get("route", 0) > 0
        return {
            # `priorities` used to be here and in the response schema. Nothing ever read
            # it — the model spent tokens filling a field with no consumer, and in run 2
            # returned section titles where the fallback implies an ordered doc-type
            # list. Removed rather than wired: fan-out order is not a strategy decision.
            "audiences": [
                {"doc_type": dt, "audience": "developers", "tone": "technical"}
                for dt in doc_types
            ],
            "generate_diagrams": bool(worth_drawing),
        }
