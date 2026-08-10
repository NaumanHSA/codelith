from __future__ import annotations

import io
import zipfile

import yaml

from codelith.apps.documentation.formatters.site_tree import SiteTree, rewrite_links, slugify_filename
from codelith.models.document import Document

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
            "---",
            f"title: \"{doc.title}\"",
            "---",
            "",
            doc.content_markdown or "*No content generated.*",
        ]
        return "\n".join(lines)

    # ── Site tree ─────────────────────────────────────────────────────────────

    def format_site_tree(self, tree: SiteTree) -> bytes:
        """
        A real MkDocs site: a directory per section and a nested `nav:`.

        This is what the formatter was always shaped for and never had. The flat
        `format_site` above stays for the legacy one-document-per-type path.

        Planned pages are skipped rather than exported empty: an export is a
        publishable artefact, and a nav entry opening onto "not written yet" is
        worse for a reader than one page fewer.
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            nav: list[dict] = [{"Home": "index.md"}]

            for section in tree.sections:
                written = [p for p in section.pages if p.content_markdown.strip()]
                if not written:
                    continue
                folder = slugify_filename(section.slug)
                entries: list[dict] = []
                for page in written:
                    name = f"{slugify_filename(page.slug)}.md"
                    path = f"{folder}/{name}"
                    entries.append({page.title: path})
                    zf.writestr(
                        f"docs/{path}",
                        "---\n"
                        f'title: "{page.title}"\n'
                        "---\n\n"
                        + rewrite_links(page.content_markdown, from_page=page.address),
                    )
                nav.append({section.title: entries})

            zf.writestr("docs/index.md", self._home(tree))
            zf.writestr(
                "mkdocs.yml",
                yaml.dump(
                    {
                        "site_name": tree.title,
                        "theme": {"name": "material"},
                        "nav": nav,
                        "markdown_extensions": [
                            "admonition",
                            "pymdownx.highlight",
                            "pymdownx.superfences",
                        ],
                    },
                    default_flow_style=False,
                    sort_keys=False,
                ),
            )
        return buf.getvalue()

    @staticmethod
    def _home(tree: SiteTree) -> str:
        parts = [f"# {tree.title}", ""]
        if tree.home_markdown:
            parts += [tree.home_markdown, ""]
        for section in tree.sections:
            written = [p for p in section.pages if p.content_markdown.strip()]
            if not written:
                continue
            parts.append(f"## {section.title}")
            parts.append("")
            for page in written:
                link = f"{slugify_filename(section.slug)}/{slugify_filename(page.slug)}.md"
                intent = f" — {page.intent}" if page.intent else ""
                parts.append(f"- [{page.title}]({link}){intent}")
            parts.append("")
        return "\n".join(parts)
