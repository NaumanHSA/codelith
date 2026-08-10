"""
Saving what was written.

Two destinations, decided per document by whether the writer stamped a `page_id` on
it:

  * **`doc_pages`** — a page of the project's documentation site, written back with
    the provenance that makes it auditable: the job, the knowledge base, the commit,
    and the source files it was actually anchored on.
  * **`documents`** — the original one-row-per-document path, unchanged.

Nothing here decides which; the scope on the job did, back in `kb_loader`.
"""

from typing import Any

from codelith.agents.base import BaseAgent
from codelith.services.audit_service import AuditService
from codelith.apps.documentation.services.document_service import DocumentService
from codelith.apps.documentation.services.site_service import SiteService
from codelith.knowledge.grounding import check_page, vocabulary_for
from codelith.tracing.artifacts import save_artifact, save_text_artifact


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
            generated_docs: list[dict] = (
                state.get("formatted_docs")
                or state.get("linked_docs")
                or state.get("generated_docs")
                or []
            )
            export_keys: dict[str, list[str]] = state.get("export_keys", {})

            # Pages and legacy documents never mix within one job — a job either has
            # a page scope or it does not — so an early return keeps the two paths
            # from having to know about each other. Note the mode is decided by the
            # *scope*, not by what came back: a job whose every writer failed still
            # has pages to mark failed.
            if state.get("pages"):
                saved_page_ids = await self._publish_pages(state, generated_docs)
                await self._audit(job, saved_page_ids, kind="page")
                self._save_artifacts(generated_docs, saved_page_ids, key="address")
                t.outputs(saved_page_ids=saved_page_ids)
                await self._update_step(
                    self.name, "completed", {"saved_page_ids": saved_page_ids}
                )
                await self.db.commit()
                return {"saved_page_ids": saved_page_ids, "saved_doc_ids": []}

            doc_svc = DocumentService(self.db)
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

            await self._audit(job, saved_doc_ids, kind="document")
            self._save_artifacts(generated_docs, saved_doc_ids, key="doc_type")

            t.outputs(saved_doc_ids=saved_doc_ids)
            await self._update_step(self.name, "completed", {"saved_doc_ids": saved_doc_ids})
            await self.db.commit()
            return {"saved_doc_ids": saved_doc_ids}

    # ── Pages ─────────────────────────────────────────────────────────────────

    async def _publish_pages(self, state: dict[str, Any], docs: list[dict]) -> list[int]:
        """
        Write each generated page back onto its `doc_pages` row.

        A page that produced nothing is marked failed rather than left `generating`,
        which would strand it in a spinner forever. Pages claimed by this job that
        the writer never reached are swept the same way — a crashed fan-out branch
        must not leave the nav lying about what is happening.
        """
        sites = SiteService(self.db)
        saved: list[int] = []
        written: set[int] = set()
        # QA ran per page, so its verdict lands on the page. One score for a
        # twenty-page document was decorative; per page it names what to look at.
        reviews = self._reviews(state)
        # Everything this knowledge base can name, built once for the run. The
        # check is per page but the vocabulary is not, and assembling it per page
        # would re-read every module for each one.
        known = await self._grounding_vocabulary(state)
        for doc in (d for d in docs if d.get("page_id")):
            page_id = doc["page_id"]
            written.add(page_id)
            content = (doc.get("content_markdown") or "").strip()
            if not content:
                await sites.fail_page(page_id, self.job_id)
                await self._emit_log("warning", f"Page {doc['address']} produced no content")
                continue
            await sites.publish_page(
                page_id,
                content_markdown=content,
                job_id=self.job_id,
                kb_id=state.get("kb_id"),
                commit_sha=state.get("commit_sha"),
                source_files=doc.get("source_files") or [],
                qa=reviews.get(doc["address"]),
                grounding=(
                    check_page(content, known).to_dict() if known else None
                ),
            )
            saved.append(page_id)
            await self._emit_log("info", f"Saved page: {doc['address']}", page_id=page_id)

        for claimed in state.get("pages") or []:
            if claimed["id"] not in written:
                await sites.fail_page(claimed["id"], self.job_id)
                await self._emit_log("warning", f"Page {claimed['address']} was never written")

        return saved

    async def _grounding_vocabulary(self, state: dict[str, Any]) -> frozenset[str]:
        """
        What the codebase can name, or an empty set when there is no KB to ask.

        Empty disables the check rather than failing it: the legacy single-shot
        pipeline has no knowledge base, and a page written by it is not less
        trustworthy for our being unable to measure it.
        """
        kb_id = state.get("kb_id")
        project = state.get("project")
        if not kb_id or project is None:
            return frozenset()
        try:
            return await vocabulary_for(self.db, kb_id, project.id)
        except Exception as exc:  # pragma: no cover - never fail a publish for this
            await self._emit_log("info", f"Grounding not measured: {exc}")
            return frozenset()

    @staticmethod
    def _reviews(state: dict[str, Any]) -> dict[str, dict]:
        """
        QA's verdict per page address, folded together from its two result lists.

        `review_results` carries the score and the issues; `validation_results`
        carries the claim checks. A reader wants both in one place — "7/10, 4 of 5
        claims verified" — and neither is useful without the other.
        """
        by_address: dict[str, dict] = {}
        for entry in state.get("review_results") or []:
            if address := entry.get("address"):
                review = entry.get("review") or {}
                by_address[address] = {
                    "score": review.get("score"),
                    "approved": review.get("approved"),
                    "issues": review.get("issues") or [],
                }
        for entry in state.get("validation_results") or []:
            if (address := entry.get("address")) and address in by_address:
                by_address[address] |= {
                    "claims_checked": entry.get("claims_checked", 0),
                    "claims_passed": entry.get("claims_passed", 0),
                }
        return by_address

    # ── Shared ────────────────────────────────────────────────────────────────

    async def _audit(self, job, ids: list[int], *, kind: str) -> None:
        await AuditService(self.db).log(
            action="document.publish",
            resource_type="job",
            user_id=getattr(job, "created_by", None),
            resource_id=self.job_id,
            details={"kind": kind, "doc_count": len(ids), "doc_ids": ids},
            commit=False,
        )

    @staticmethod
    def _save_artifacts(docs: list[dict], ids: list[int], *, key: str) -> None:
        for doc in docs:
            save_text_artifact(
                f"publisher.{doc.get(key) or doc.get('doc_type')}.published",
                doc.get("content_markdown") or "",
            )
        save_artifact(
            "publisher.documents",
            [
                {"id": i, "doc_type": d.get("doc_type"), "title": d.get("title"),
                 "address": d.get("address")}
                for d, i in zip(docs, ids, strict=False)
            ],
        )
