from __future__ import annotations

from typing import Any

import structlog

from codelith.agents.base import BaseAgent
from codelith.knowledge.sites import doc_key
from codelith.tracing.artifacts import save_artifact

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
            generated_docs: list[dict] = (
                state.get("linked_docs") or state.get("generated_docs") or []
            )
            diagrams: list[dict] = state.get("diagrams", [])
            output_formats: list[str] = state.get("output_formats", ["markdown"])

            # ── Enrich markdown (inject diagrams + frontmatter) ────────────────
            formatted_docs = []
            for doc in generated_docs:
                content = doc.get("content_markdown", "")
                # Diagrams carry the doc_type they were drawn for. Injecting only into
                # `architecture` meant every diagram generated for an API or deployment
                # document was produced and then silently discarded.
                mine = [d for d in diagrams if d.get("doc_key") == doc_key(doc)]
                if mine:
                    content = self._inject_diagrams(content, mine)
                # Frontmatter is deliberately not injected. What this list becomes is
                # the page the publisher stores, so injecting it meant a packaging
                # choice made before anything was written had rewritten the source of
                # truth — pick MkDocs at compose time and every stored page grew a
                # YAML preamble it should never have carried.
                #
                # It was redundant as well as harmful: `MkDocsFormatter` and
                # `DocusaurusFormatter` both write their own frontmatter at export
                # time, from the same clean markdown. That is what makes "one stored
                # form, any format" true rather than nearly true.
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

            save_artifact(
                "formatter.result",
                {
                    "formats": list(output_formats),
                    "export_keys": export_keys,
                    "diagrams_injected": self._diagram_count(diagrams),
                    "documents": [
                        {
                            "doc_type": d.get("doc_type"),
                            "address": d.get("address"),
                            "title": d.get("title"),
                            "chars": len(d.get("content_markdown") or ""),
                        }
                        for d in formatted_docs
                    ],
                },
            )

            t.outputs(formats=list(output_formats), exports=export_keys)
            await self._update_step(self.name, "completed", {
                "formats": list(output_formats),
                "export_keys": export_keys,
            })
            # Use formatted_docs (a regular list key) instead of re-emitting generated_docs
            # through the Annotated operator.add reducer, which would double the list.
            return {"formatted_docs": formatted_docs, "export_keys": export_keys}

    async def _generate_export(self, fmt: str, docs: list[dict], project) -> list[str]:
        from codelith.storage.s3 import StorageClient
        storage = StorageClient()
        keys: list[str] = []
        pid = project.id
        pname = project.name

        if fmt == "docx":
            from codelith.apps.documentation.formatters.docx import DocxFormatter
            formatter = DocxFormatter()
            for doc_dict in docs:
                # Build a lightweight Document-like object
                doc = _DictDoc(doc_dict)
                data = formatter.format(doc)
                key = f"exports/{pid}/{_slug(doc_key(doc_dict))}.docx"
                await storage.upload_bytes(data, key, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                keys.append(key)

        elif fmt == "mkdocs":
            from codelith.apps.documentation.formatters.mkdocs import MkDocsFormatter
            docs_objs = [_DictDoc(d) for d in docs]
            data = MkDocsFormatter().format_site(docs_objs, pname)
            key = f"exports/{pid}/mkdocs-site.zip"
            await storage.upload_bytes(data, key, "application/zip")
            keys.append(key)

        elif fmt == "docusaurus":
            from codelith.apps.documentation.formatters.docusaurus import DocusaurusFormatter
            docs_objs = [_DictDoc(d) for d in docs]
            data = DocusaurusFormatter().format_site(docs_objs, pname)
            key = f"exports/{pid}/docusaurus-site.zip"
            await storage.upload_bytes(data, key, "application/zip")
            keys.append(key)

        return keys

    # ── Markdown enrichment ────────────────────────────────────────────────────

    def _inject_diagrams(self, content: str, diagrams: list[dict]) -> str:
        """
        Show the picture; keep the source.

        A fenced ```mermaid block is only a diagram if the reader renders Mermaid, and
        neither the studio's markdown pipeline nor a DOCX export does — so a generated
        diagram reached the reader as a wall of `graph TD` text. The rendered PNG is
        embedded as a data URI, which survives being copied into any export without
        needing an asset server or a second request, and the Mermaid source follows it
        in a collapsed block so it stays editable.
        """
        section = "\n\n## Diagrams\n"
        for d in diagrams:
            language = d.get("language") or "mermaid"
            section += f"\n### {d['name']}\n\n"
            if svg := d.get("svg_base64"):
                # SVG for the graph-derived diagrams: roughly a tenth the size of the
                # equivalent PNG in a data URI, crisp at any zoom, and themeable
                # rather than baked onto a white rectangle.
                section += f"![{d['name']}](data:image/svg+xml;base64,{svg})\n\n"
                section += (
                    "<details>\n<summary>Diagram source</summary>\n\n"
                    f"```{language}\n{d['content']}\n```\n\n</details>\n"
                )
            elif png := d.get("png_base64"):
                section += f"![{d['name']}](data:image/png;base64,{png})\n\n"
                section += (
                    "<details>\n<summary>Diagram source</summary>\n\n"
                    f"```{language}\n{d['content']}\n```\n\n</details>\n"
                )
            else:
                # Nothing rendered it — the source is better than nothing.
                section += f"```{language}\n{d['content']}\n```\n"
        return content + section

    @staticmethod
    def _diagram_count(diagrams: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in diagrams:
            key = d.get("doc_key") or d.get("doc_type") or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts

def _slug(key: str) -> str:
    """
    An export filename for one document.

    A page address contains a slash, which would silently write into a nested S3
    prefix — and two pages of the same `doc_type` would otherwise overwrite each
    other, which is exactly what page mode makes commonplace.
    """
    return key.replace("/", "-") or "document"


class _DictDoc:
    """Lightweight stand-in for a Document ORM object when working with dicts."""
    def __init__(self, d: dict) -> None:
        self.title = d.get("title", "")
        self.doc_type = d.get("doc_type", "")
        self.content_markdown = d.get("content_markdown", "")
        self.version = d.get("version", 1)
