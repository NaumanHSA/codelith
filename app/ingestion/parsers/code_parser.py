from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.languages.registry import registry

#: Languages we can ingest but do not understand structurally. Files with these
#: extensions are read, chunked and made searchable; they have no `LanguageProvider`,
#: so they contribute no symbols, modules or entities.
#:
#: Kept deliberately broad. "Is this source code?" and "can we parse it?" are
#: different questions, and a Go repository is better served by searchable chunks
#: than by being ignored entirely.
_UNPARSED_EXTENSIONS: dict[str, str] = {
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cs": "c_sharp",
    ".rb": "ruby",
    ".php": "php",
    ".cpp": "cpp",
    ".c": "c",
    ".kt": "kotlin",
}


def _supported_extensions() -> dict[str, str]:
    """
    Every extension worth reading: whatever the providers own, plus the rest.

    Derived from the registry rather than hand-listed, because the hand-listed
    version drifted. `.pyi`, `.mjs`, `.cjs`, `.mts` and `.cts` all had providers and
    were never ingested — the provider existed, the files never reached it, and
    nothing failed loudly. Adding a language must not require remembering this file.
    """
    out = dict(_UNPARSED_EXTENSIONS)
    for provider in registry.providers():
        for extension in provider.extensions:
            out[extension.lower()] = provider.language
    return out


#: Extension → language. Computed at import, after providers are registered.
SUPPORTED_EXTENSIONS: dict[str, str] = _supported_extensions()

IGNORED_DIRS = {
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".pytest_cache", "dist", "build", ".eggs", "coverage",
}


@dataclass
class ParsedFile:
    path: str
    language: str
    content: str
    size_bytes: int
    symbols: list[dict] = field(default_factory=list)  # {type, name, line, docstring}


@dataclass
class ParsedCodebase:
    root_path: str
    files: list[ParsedFile] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)  # lang → file count

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def primary_language(self) -> str | None:
        if not self.languages:
            return None
        return max(self.languages, key=lambda k: self.languages[k])


class CodeParser:
    def parse_directory(self, root: Path, max_file_size_kb: int = 500) -> ParsedCodebase:
        result = ParsedCodebase(root_path=str(root))

        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in IGNORED_DIRS for part in file_path.parts):
                continue

            ext = file_path.suffix.lower()
            language = SUPPORTED_EXTENSIONS.get(ext)
            if not language:
                continue

            size = file_path.stat().st_size
            if size > max_file_size_kb * 1024:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            symbols = self._extract_symbols(content, language, file_path)
            parsed = ParsedFile(
                path=file_path.relative_to(root).as_posix(),
                language=language,
                content=content,
                size_bytes=size,
                symbols=symbols,
            )
            result.files.append(parsed)
            result.languages[language] = result.languages.get(language, 0) + 1

        return result

    def _extract_symbols(self, content: str, language: str, path: Path) -> list[dict]:
        """Best-effort symbol extraction using simple heuristics (tree-sitter in Phase 3)."""
        symbols: list[dict] = []
        lines = content.splitlines()

        if language == "python":
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("def ") or stripped.startswith("async def "):
                    name = stripped.split("(")[0].split()[-1]
                    symbols.append({"type": "function", "name": name, "line": i})
                elif stripped.startswith("class "):
                    name = stripped.split("(")[0].split()[-1].rstrip(":")
                    symbols.append({"type": "class", "name": name, "line": i})

        elif language in ("javascript", "typescript"):
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if "function " in stripped:
                    parts = stripped.split("function ")
                    if len(parts) > 1:
                        name = parts[1].split("(")[0].strip()
                        if name:
                            symbols.append({"type": "function", "name": name, "line": i})
                elif stripped.startswith("class "):
                    name = stripped.split("{")[0].split()[-1]
                    symbols.append({"type": "class", "name": name, "line": i})

        return symbols
