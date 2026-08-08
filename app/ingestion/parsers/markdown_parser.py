from dataclasses import dataclass
from pathlib import Path

from app.languages.registry import registry


@dataclass
class ParsedMarkdown:
    #: Repository-relative, POSIX-separated — the same address space as code chunks.
    path: str
    content: str
    headings: list[str]
    size_bytes: int


class MarkdownParser:
    def parse_file(self, path: Path, root: Path | None = None) -> ParsedMarkdown:
        content = path.read_text(encoding="utf-8", errors="ignore")
        headings = [
            line.lstrip("#").strip()
            for line in content.splitlines()
            if line.startswith("#")
        ]
        return ParsedMarkdown(
            path=_relative(path, root),
            content=content,
            headings=headings,
            size_bytes=path.stat().st_size,
        )

    def parse_directory(self, root: Path) -> list[ParsedMarkdown]:
        results = []
        for md_path in root.rglob("*.md"):
            relative = _relative(md_path, root)
            # `node_modules`, `.venv` and `site-packages` are full of markdown that
            # documents somebody else's software. Indexed, it answers questions about
            # a dependency as though it were about this project.
            if registry.should_skip(relative):
                continue
            try:
                results.append(self.parse_file(md_path, root))
            except OSError:
                continue
        return results


def _relative(path: Path, root: Path | None) -> str:
    """
    A path in the same address space as every other chunk.

    Absolute native paths were being stored verbatim, so a prose chunk read
    `repos\\54816587-…\\docs\\index.md` while the code beside it read
    `neurosurfer/config.py`. Nothing could join the two — which is the whole point
    of indexing prose, since its value is pointing at code — and the stored path
    leaked the sandbox directory into the knowledge base.
    """
    if root is not None:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            pass
    return path.as_posix()
