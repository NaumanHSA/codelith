from typing import Any
from app.agents.base import BaseAgent
from app.services.document_service import DocumentService
from app.services.audit_service import AuditService


class PublisherAgent(BaseAgent):
    name = "publisher_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="PublisherAgent: saving documents",
            end_message="PublisherAgent: complete",
        ) as t:
            await self._emit_log("info", "PublisherAgent: saving documents")
            await self._update_step(self.name, "running")

            project = state["project"]
            job = state["job"]
            # Use formatter's diagram-enriched copy when available
            generated_docs: list[dict] = state.get("formatted_docs") or state.get("generated_docs", [])
            export_keys: dict[str, list[str]] = state.get("export_keys", {})

            doc_svc = DocumentService(self.db)
            audit = AuditService(self.db)
            saved_doc_ids: list[int] = []

            for doc in generated_docs:
                saved = await doc_svc.create(
                    project_id=project.id,
                    job_id=self.job_id,
                    doc_type=doc["doc_type"],
                    title=doc["title"],
                    content_markdown=doc.get("content_markdown"),
                )
                saved_doc_ids.append(saved.id)
                await self._emit_log("info", f"Saved document: {doc['title']}", doc_id=saved.id)

                # Create DocumentExport records for S3-uploaded formats
                for fmt, keys in export_keys.items():
                    matching = [k for k in keys if doc["doc_type"] in k]
                    for key in matching:
                        await doc_svc.create_export(
                            document_id=saved.id,
                            format=fmt,
                            storage_path=key,
                        )

            # Audit log: document publish event
            await audit.log(
                action="document.publish",
                resource_type="job",
                user_id=getattr(job, "created_by", None),
                resource_id=self.job_id,
                details={"doc_count": len(saved_doc_ids), "doc_ids": saved_doc_ids},
                commit=False,
            )

            t.outputs(saved_doc_ids=saved_doc_ids)
            await self._update_step(self.name, "completed", {"saved_doc_ids": saved_doc_ids})
            await self.db.commit()
            return {"saved_doc_ids": saved_doc_ids}
