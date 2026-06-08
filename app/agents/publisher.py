from typing import Any
from app.agents.base import BaseAgent
from app.services.document_service import DocumentService


class PublisherAgent(BaseAgent):
    name = "publisher_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        await self._emit_log("info", "PublisherAgent: saving documents")
        await self._update_step(self.name, "running")

        project = state["project"]
        job_id = self.job_id
        generated_docs: list[dict] = state.get("generated_docs", [])

        svc = DocumentService(self.db)
        saved_doc_ids = []

        for doc in generated_docs:
            saved = await svc.create(
                project_id=project.id,
                job_id=job_id,
                doc_type=doc["doc_type"],
                title=doc["title"],
                content_markdown=doc.get("content_markdown"),
            )
            saved_doc_ids.append(saved.id)
            await self._emit_log("info", f"Saved document: {doc['title']}", doc_id=saved.id)

        await self._update_step(self.name, "completed", {"saved_doc_ids": saved_doc_ids})
        return {**state, "saved_doc_ids": saved_doc_ids}
