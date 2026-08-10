"""
What QA derives for itself, that the shared analysis has no business carrying.

Q2 discovered the need rather than assuming it. The knowledge base stores symbols per
*module*, and a module is usually several files — so a finding at `config/mcp.py:127`
cannot be attributed to a symbol, because the symbol list belonging to the
`neurosurfer.config` module could be from any of its files. On neurosurfer that made
symbol attribution possible for almost nothing.

Adding file attribution to the shared analysis would make **every** project pay, in
time and storage, for something only QA reads. So QA derives it, from the checkout it
already has, keyed to the same commit.

**This is the first app with two stages, and the shape generalises.** An app is defined
by what it reads from the knowledge base *and*, optionally, what it derives for itself.
The seam that matters: the derived data lives in QA's own tables, nothing in
`codelith/knowledge/` learns it exists, and a project that never opens Quality never
pays for it.

**Chosen as a lazy step, not a job type.** The plan left this open. A job is more honest
about costing minutes — but this pass is a parse of files already on disk during a QA
run, and it costs seconds rather than minutes. A second job type for something that
finishes before the first one has flushed its logs would be ceremony.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from codelith.languages.registry import registry

logger = structlog.get_logger(__name__)

#: Files parsed in one pass. A repository of ten thousand files would spend longer here
#: than on the linters, and the value falls off long before the ceiling.
_MAX_FILES = 1500


@dataclass(slots=True)
class SymbolSpan:
    """A symbol, and the lines it actually occupies — the thing the KB does not store."""

    name: str
    start: int
    end: int

    def contains(self, line: int) -> bool:
        return self.start <= line <= self.end


@dataclass(slots=True)
class DeepIndex:
    """
    QA's own view of the checkout, keyed to a commit.

    Deliberately small. Everything here answers a question the shared knowledge base
    cannot, and nothing here duplicates something it can.
    """

    commit_sha: str | None = None
    #: `path -> spans`, ordered by start line.
    symbols: dict[str, list[SymbolSpan]] = field(default_factory=dict)
    files_parsed: int = 0
    files_failed: int = 0

    def symbol_at(self, path: str, line: int) -> str | None:
        """
        The innermost symbol containing this line, or None outside any.

        Innermost, not first: a method inside a class is what a reader wants to be
        told, and both spans contain the line. Module-level code — imports, constants
        — is inside nothing, and gets nothing rather than the enclosing file's first
        function.
        """
        spans = self.symbols.get(path)
        if not spans:
            return None
        best: SymbolSpan | None = None
        for span in spans:
            if span.contains(line) and (best is None or span.start >= best.start):
                best = span
        return best.name if best else None


def build_index(root: Path, commit_sha: str | None = None) -> DeepIndex:
    """
    Walk the checkout and record where every symbol begins and ends.

    Python only for now, and by the same rule as Q1: the language decides. A parse
    failure is one file skipped, not a failed pass — a repository with one unparseable
    file still deserves the other nine hundred.
    """
    index = DeepIndex(commit_sha=commit_sha)

    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if registry.should_skip(relative):
            continue
        if index.files_parsed >= _MAX_FILES:
            logger.info("qa_deep_index_truncated", limit=_MAX_FILES)
            break

        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, RecursionError, OSError):
            index.files_failed += 1
            continue

        spans = _spans(tree)
        if spans:
            index.symbols[relative] = spans
        index.files_parsed += 1

    logger.info(
        "qa_deep_index",
        files=index.files_parsed,
        failed=index.files_failed,
        symbols=sum(len(s) for s in index.symbols.values()),
    )
    return index


def _spans(tree: ast.Module) -> list[SymbolSpan]:
    """Every function and class, qualified by its parent, with its real line range."""
    spans: list[SymbolSpan] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if not isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            name = f"{prefix}.{child.name}" if prefix else child.name
            # `end_lineno` is what makes this worth doing: the knowledge base records
            # only where a symbol starts, so it cannot tell whether a line is inside
            # one or in the gap after it.
            end = getattr(child, "end_lineno", None) or child.lineno
            spans.append(SymbolSpan(name=name, start=child.lineno, end=end))
            walk(child, name)

    walk(tree, "")
    return sorted(spans, key=lambda s: (s.start, -s.end))


__all__ = ["DeepIndex", "SymbolSpan", "build_index"]
