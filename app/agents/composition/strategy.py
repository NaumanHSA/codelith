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
from app.llm.prompts.composition_prompts import COMPOSITION_STRATEGY


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

            overview = await repos.narratives.get(kb_id, NarrativeTopic.OVERVIEW)
            architecture = await repos.narratives.get(kb_id, NarrativeTopic.ARCHITECTURE)

            messages = COMPOSITION_STRATEGY.render(
                project_name=project.name,
                doc_types=", ".join(doc_types),
                overview=(overview.content_md[:1500] if overview else "(none)"),
                architecture=(architecture.content_md[:1500] if architecture else "(none)"),
                roles=json.dumps(stats.get("roles", {})),
                facts=json.dumps(stats.get("entity_kinds", {})),
            )

            strategy = await self._call_llm_json(messages, task_type="plan")
            if not strategy or not isinstance(strategy, dict):
                strategy = self._default(doc_types, stats)
                await self._emit_log("warning", "Strategy fell back to defaults")

            strategy.setdefault("audiences", self._default(doc_types, stats)["audiences"])
            strategy.setdefault("generate_diagrams", True)

            t.outputs(doc_types=doc_types, diagrams=strategy.get("generate_diagrams"))
            await self._update_step(self.name, "completed", {"doc_types": doc_types})
            return {"strategy": strategy}

    @staticmethod
    def _default(doc_types: list[str], stats: dict) -> dict:
        roles = stats.get("roles", {})
        # Diagrams only pay off when there is real structure to draw.
        worth_drawing = len(roles) >= 3 or stats.get("entity_kinds", {}).get("route", 0) > 0
        return {
            "audiences": [
                {"doc_type": dt, "audience": "developers", "tone": "technical"}
                for dt in doc_types
            ],
            "priorities": doc_types,
            "generate_diagrams": bool(worth_drawing),
        }
