from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParsedMarkdown:
    path: str
    content: str
    headings: list[str]
    size_bytes: int


class MarkdownParser:
    def parse_file(self, path: Path) -> ParsedMarkdown:
        content = path.read_text(encoding="utf-8", errors="ignore")
        headings = [
            line.lstrip("#").strip()
            for line in content.splitlines()
            if line.startswith("#")
        ]
        return ParsedMarkdown(
            path=str(path),
            content=content,
            headings=headings,
            size_bytes=path.stat().st_size,
        )

    def parse_directory(self, root: Path) -> list[ParsedMarkdown]:
        results = []
        for md_path in root.rglob("*.md"):
            try:
                results.append(self.parse_file(md_path))
            except OSError:
                continue
        return results
