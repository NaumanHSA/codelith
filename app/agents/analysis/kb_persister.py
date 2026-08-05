"""
Seals the knowledge base.

Records aggregate stats, works out whether the build is fully READY or only
DEGRADED, and marks older builds for the project stale. A degraded build is still
usable — composition proceeds with a warning rather than the user losing an entire
analysis because a handful of module summaries failed.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.constants import KBStatus
from app.knowledge.roles import suggest_doc_types
from app.tracing.artifacts import save_artifact


class KBPersisterAgent(BaseAgent):
    name = "kb_persister_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="KBPersister: finalising knowledge base",
            end_message="KBPersister: complete",
        ) as t:
            await self._update_step(self.name, "running")

            kb_id = state["kb_id"]
            repos = KnowledgeRepositories.for_session(self.db)

            modules = await repos.modules.list_by_kb(kb_id, include_tests=True)
            roles = await repos.modules.role_breakdown(kb_id)
            entity_kinds = await repos.entities.kind_breakdown(kb_id)
            topics = await repos.narratives.topics_present(kb_id)
            missing_summaries = await repos.modules.count_missing_summaries(kb_id)

            languages = sorted({m.language for m in modules if m.language})
            stats = {
                "modules": len(modules),
                "entities": sum(entity_kinds.values()),
                "entity_kinds": entity_kinds,
                "roles": roles,
                "narratives": sorted(topics),
                "languages": languages,
                "indexed_chunks": state.get("indexed_chunks", 0),
                "summarised_modules": state.get("summarised_modules", 0),
                "missing_summaries": missing_summaries,
                "suggested_doc_types": suggest_doc_types(entity_kinds, roles),
            }

            reasons = self._degradation_reasons(state, modules, topics, missing_summaries)
            status = KBStatus.DEGRADED if reasons else KBStatus.READY

            save_artifact(
                "kb_persister.kb_stats",
                {"kb_id": kb_id, "status": str(status), "degraded_because": reasons, **stats},
            )

            await repos.bases.finish_build(
                kb_id,
                status=status,
                stats=stats,
                error="; ".join(reasons) if reasons else None,
            )
            await self.db.commit()

            await self._emit_log(
                "info",
                f"Knowledge base {status} — {len(modules)} modules, "
                f"{stats['entities']} facts, {len(topics)} narratives",
                **{k: v for k, v in stats.items() if k != "suggested_doc_types"},
            )
            t.outputs(kb_id=kb_id, status=str(status), **{"modules": len(modules)})
            await self._update_step(
                self.name, "completed", {"kb_id": kb_id, "status": str(status)}
            )

            return {"kb_id": kb_id, "kb_status": str(status), "kb_stats": stats}

    @staticmethod
    def _degradation_reasons(
        state: dict[str, Any], modules, topics: set[str], missing_summaries: int
    ) -> list[str]:
        reasons: list[str] = []
        if not modules:
            reasons.append("no modules were extracted")
        if state.get("architecture_degraded"):
            reasons.append("architecture map came from the deterministic fallback")
        if not topics:
            reasons.append("no narratives were produced")
        if state.get("summary_failures"):
            reasons.append(f"{state['summary_failures']} module summaries failed")
        if state.get("narrative_failures"):
            reasons.append(f"{state['narrative_failures']} narratives failed")
        if not state.get("indexed_chunks"):
            reasons.append("no chunks were embedded — semantic retrieval unavailable")
        return reasons
