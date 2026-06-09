from typing import Any

from app.agents.base import BaseAgent


class FormatterAgent(BaseAgent):
    name = "formatter_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        await self._emit_log("info", "FormatterAgent: post-processing documents")
        await self._update_step(self.name, "running")

        project = state["project"]
        generated_docs: list[dict] = state.get("generated_docs", [])
        diagrams: list[dict] = state.get("diagrams", [])
        output_formats: list[str] = state.get("output_formats", ["markdown"])

        formatted_docs = []
        for doc in generated_docs:
            content = doc.get("content_markdown", "")

            # Inject diagrams into architecture docs
            if doc.get("doc_type") == "architecture" and diagrams:
                content = self._inject_diagrams(content, diagrams)

            # Add YAML front-matter for MkDocs / Docusaurus compatibility
            if "mkdocs" in output_formats or "docusaurus" in output_formats:
                content = self._add_frontmatter(doc, content)

            formatted_docs.append({**doc, "content_markdown": content})

        await self._update_step(self.name, "completed", {"formatted": len(formatted_docs)})
        return {**state, "generated_docs": formatted_docs}

    def _inject_diagrams(self, content: str, diagrams: list[dict]) -> str:
        diagram_section = "\n\n## Diagrams\n"
        for d in diagrams:
            diagram_section += f"\n### {d['name']}\n\n```mermaid\n{d['content']}\n```\n"
        return content + diagram_section

    def _add_frontmatter(self, doc: dict, content: str) -> str:
        title = doc.get("title", "Documentation")
        doc_type = doc.get("doc_type", "doc")
        frontmatter = f"---\ntitle: \"{title}\"\ncategory: {doc_type}\n---\n\n"
        return frontmatter + content
