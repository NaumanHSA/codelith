from typing import Any
from app.agents.base import BaseAgent
from app.ingestion.pipeline import IngestionPipeline


class RepoAnalyzerAgent(BaseAgent):
    name = "repo_analyzer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        await self._emit_log("info", "RepoAnalyzer: scanning project sources")
        await self._update_step(self.name, "running")

        project = state["project"]
        pipeline = IngestionPipeline(project=project, job_id=self.job_id, db=self.db)
        ingestion_result = await pipeline.run()

        # Expose codebase from the last successfully parsed source
        codebase = getattr(pipeline, "_last_codebase", None)

        await self._update_step(self.name, "completed", ingestion_result)
        await self._emit_log("info", "Sources analyzed", **ingestion_result)

        return {**state, "ingestion_result": ingestion_result, "codebase": codebase}
