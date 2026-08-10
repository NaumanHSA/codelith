from datetime import UTC, datetime
from codelith.models.document import Document


class MarkdownFormatter:
    def format(self, doc: Document) -> bytes:
        lines = [
            f"# {doc.title}",
            "",
            f"> **Type:** {doc.doc_type}  ",
            f"> **Version:** {doc.version}  ",
            f"> **Generated:** {datetime.now(UTC).strftime('%Y-%m-%d')}",
            "",
            "---",
            "",
        ]
        if doc.content_markdown:
            lines.append(doc.content_markdown)
        else:
            lines.append("*No content generated.*")

        return "\n".join(lines).encode("utf-8")
