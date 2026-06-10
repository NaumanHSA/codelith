from typing import Any
from app.agents.base import BaseAgent


class CoordinatorAgent(BaseAgent):
    name = "coordinator_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="Coordinator: analyzing job config",
            end_message="Coordinator: complete",
        ) as t:
            await self._emit_log("info", "Coordinator started — analyzing job config")
            await self._update_step(self.name, "running")

            job_config = state.get("job_config", {})
            doc_types = job_config.get("doc_types", ["architecture"])
            output_formats = job_config.get("output_formats", ["markdown"])
            requires_human_review = job_config.get("human_review", False)

            t.outputs(doc_types=doc_types, output_formats=output_formats)
            await self._update_step(self.name, "completed", {"doc_types": doc_types})

            return {
                "doc_types": doc_types,
                "output_formats": output_formats,
                "requires_human_review": requires_human_review,
                "generated_docs": [],
            }
