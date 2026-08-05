from __future__ import annotations

from typing import Any

import structlog

from app.agents.base import BaseAgent

logger = structlog.get_logger(__name__)


class FormatterAgent(BaseAgent):
    name = "formatter_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="FormatterAgent: post-processing and exporting documents",
            end_message="FormatterAgent: complete",
        ) as t:
            await self._emit_log("info", "FormatterAgent: post-processing documents")
            await self._update_step(self.name, "running")

            project = state["project"]
            generated_docs: list[dict] = state.get("generated_docs", [])
            diagrams: list[dict] = state.get("diagrams", [])
            output_formats: list[str] = state.get("output_formats", ["markdown"])

            # ── Enrich markdown (inject diagrams + frontmatter) ────────────────
            formatted_docs = []
            for doc in generated_docs:
                content = doc.get("content_markdown", "")
                if doc.get("doc_type") == "architecture" and diagrams:
                    content = self._inject_diagrams(content, diagrams)
                if "mkdocs" in output_formats or "docusaurus" in output_formats:
                    content = self._add_frontmatter(doc, content)
                formatted_docs.append({**doc, "content_markdown": content})

            # ── Generate non-markdown exports ──────────────────────────────────
            export_keys: dict[str, list[str]] = {}  # format → list of S3 keys
            for fmt in output_formats:
                if fmt == "markdown":
                    continue
                try:
                    keys = await self._generate_export(fmt, formatted_docs, project)
                    export_keys[fmt] = keys
                    await self._emit_log("info", f"Export generated: {fmt}", files=len(keys))
                except Exception as exc:
                    await self._emit_log("warning", f"Export failed for {fmt}: {exc}")

            t.outputs(formats=list(output_formats), exports=export_keys)
            await self._update_step(self.name, "completed", {
                "formats": list(output_formats),
                "export_keys": export_keys,
            })
            # Use formatted_docs (a regular list key) instead of re-emitting generated_docs
            # through the Annotated operator.add reducer, which would double the list.
            return {"formatted_docs": formatted_docs, "export_keys": export_keys}

    async def _generate_export(self, fmt: str, docs: list[dict], project) -> list[str]:
        from app.storage.s3 import StorageClient
        storage = StorageClient()
        keys: list[str] = []
        pid = project.id
        pname = project.name

        if fmt == "docx":
            from app.formatters.docx import DocxFormatter
            formatter = DocxFormatter()
            for doc_dict in docs:
                # Build a lightweight Document-like object
                doc = _DictDoc(doc_dict)
                data = formatter.format(doc)
                key = f"exports/{pid}/{doc_dict['doc_type']}.docx"
                await storage.upload_bytes(data, key, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                keys.append(key)

        elif fmt == "mkdocs":
            from app.formatters.mkdocs import MkDocsFormatter
            docs_objs = [_DictDoc(d) for d in docs]
            data = MkDocsFormatter().format_site(docs_objs, pname)
            key = f"exports/{pid}/mkdocs-site.zip"
            await storage.upload_bytes(data, key, "application/zip")
            keys.append(key)

        elif fmt == "docusaurus":
            from app.formatters.docusaurus import DocusaurusFormatter
            docs_objs = [_DictDoc(d) for d in docs]
            data = DocusaurusFormatter().format_site(docs_objs, pname)
            key = f"exports/{pid}/docusaurus-site.zip"
            await storage.upload_bytes(data, key, "application/zip")
            keys.append(key)

        return keys

    # ── Markdown enrichment ────────────────────────────────────────────────────

    def _inject_diagrams(self, content: str, diagrams: list[dict]) -> str:
        section = "\n\n## Diagrams\n"
        for d in diagrams:
            section += f"\n### {d['name']}\n\n```mermaid\n{d['content']}\n```\n"
        return content + section

    def _add_frontmatter(self, doc: dict, content: str) -> str:
        title = doc.get("title", "Documentation")
        doc_type = doc.get("doc_type", "doc")
        return f"---\ntitle: \"{title}\"\ncategory: {doc_type}\n---\n\n" + content


class _DictDoc:
    """Lightweight stand-in for a Document ORM object when working with dicts."""
    def __init__(self, d: dict) -> None:
        self.title = d.get("title", "")
        self.doc_type = d.get("doc_type", "")
        self.content_markdown = d.get("content_markdown", "")
        self.version = d.get("version", 1)
