"""
Entry point for Phase 2.

Resolves which knowledge base to compose from and unpacks the job config. This is
where the two phases meet: everything downstream reads the KB and never touches the
repository, which no longer exists on disk by this point.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.constants import KBStatus
from app.tracing.artifacts import save_artifact


class KBLoaderAgent(BaseAgent):
    name = "kb_loader_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="KBLoader: resolving knowledge base",
            end_message="KBLoader: complete",
        ) as t:
            await self._update_step(self.name, "running")

            project = state["project"]
            job_config = state.get("job_config") or {}
            repos = KnowledgeRepositories.for_session(self.db)

            kb_id = job_config.get("kb_id")
            kb = (
                await repos.bases.get_by_id(kb_id)
                if kb_id
                else await repos.bases.get_latest_usable(project.id)
            )

            if kb is None:
                raise ValueError(
                    f"Project {project.id} has no usable knowledge base — run analysis first"
                )
            if not KBStatus(kb.status).is_usable:
                raise ValueError(f"Knowledge base {kb.id} is {kb.status}, not usable")

            stats = kb.stats_json or {}
            doc_types = job_config.get("doc_types") or ["architecture"]
            output_formats = job_config.get("output_formats") or ["markdown"]

            if kb.status == KBStatus.DEGRADED:
                await self._emit_log(
                    "warning",
                    f"Composing from a degraded knowledge base: {kb.error_message}",
                )

            await self._emit_log(
                "info",
                f"Composing {doc_types} from knowledge base {kb.id}",
                modules=stats.get("modules"),
                narratives=stats.get("narratives"),
            )
            save_artifact(
                "kb_loader.resolved",
                {
                    "kb_id": kb.id,
                    "kb_status": kb.status,
                    "commit_sha": kb.commit_sha,
                    "doc_types": doc_types,
                    "output_formats": output_formats,
                    "kb_stats": stats,
                },
            )

            t.outputs(kb_id=kb.id, doc_types=doc_types, kb_status=kb.status)
            await self._update_step(
                self.name, "completed", {"kb_id": kb.id, "doc_types": doc_types}
            )

            return {
                "kb_id": kb.id,
                "kb_status": kb.status,
                "kb_stats": stats,
                "doc_types": doc_types,
                "output_formats": output_formats,
                "requires_human_review": job_config.get("human_review", False),
                "generated_docs": [],
            }
