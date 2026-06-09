from __future__ import annotations

import io
import zipfile

import yaml

from app.models.document import Document


_NAV_LABEL = {
    "architecture": "Architecture",
    "api": "API Reference",
    "module": "Module Guide",
    "tutorial": "Tutorial",
    "runbook": "Runbook",
}


class MkDocsFormatter:
    """
    Produces a ZIP containing a ready-to-serve MkDocs site:
      mkdocs.yml
      docs/index.md
      docs/{doc_type}.md  (one per document)
    """

    def format_site(self, docs: list[Document], project_name: str) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            nav = [{"Home": "index.md"}]

            for doc in docs:
                filename = f"{doc.doc_type}.md"
                label = _NAV_LABEL.get(doc.doc_type, doc.doc_type.title())
                nav.append({label: filename})
                content = self._page_content(doc)
                zf.writestr(f"docs/{filename}", content)

            # index.md
            index = f"# {project_name}\n\nWelcome to the generated documentation.\n"
            zf.writestr("docs/index.md", index)

            # mkdocs.yml
            config = {
                "site_name": project_name,
                "theme": {"name": "material"},
                "nav": nav,
                "markdown_extensions": [
                    "admonition",
                    "pymdownx.highlight",
                    "pymdownx.superfences",
                ],
            }
            zf.writestr("mkdocs.yml", yaml.dump(config, default_flow_style=False))

        return buf.getvalue()

    def _page_content(self, doc: Document) -> str:
        lines = [
            f"---",
            f"title: \"{doc.title}\"",
            f"---",
            "",
            doc.content_markdown or "*No content generated.*",
        ]
        return "\n".join(lines)
