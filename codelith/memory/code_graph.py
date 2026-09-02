"""
The code graph as plain data, before it touches a database.

Assembled by the graph builder from provider output, so it can be asserted about in
tests without any database running — which is most of what there is to get wrong.

Two rules this shape exists to hold:

* **Nothing language-specific.** Imports arrive already resolved, because turning
  `from .. import session` into a path requires knowing the language's rules.
  `LanguageProvider.resolve_import` owns that.
* **A node only for something that exists.** External import targets are packages,
  not files; unresolvable ones are dropped. A graph mostly composed of files that are
  not in the repository is worse than a smaller true one.

Scoped by `kb_id`, not just `project_id`: a knowledge base is pinned to a commit, and
two analyses of the same repository at different commits must not merge into one
graph. Deleting a knowledge base deletes its subgraph.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GraphScope:
    """Which analysis a subgraph belongs to."""

    project_id: int
    kb_id: int | None = None
    commit_sha: str | None = None


@dataclass(slots=True)
class CodeGraph:
    """
    The graph as plain data, before it touches a database.

    Assembled by the graph builder from provider output, so it can be asserted about
    in tests without Neo4j running — which is most of what there is to get wrong.
    """

    #: {path, language, module_key, loc}
    files: list[dict] = field(default_factory=list)
    #: {key, name, role}
    modules: list[dict] = field(default_factory=list)
    #: {path, qname, name, kind, line, end_line, visibility}
    symbols: list[dict] = field(default_factory=list)
    #: {src, dst} — both repository paths
    imports: list[dict] = field(default_factory=list)
    #: {src, name} — a file and the external package it depends on
    packages: list[dict] = field(default_factory=list)
    #: {src_path, src_qname, dst_path, dst_qname}
    calls: list[dict] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "files": len(self.files),
            "modules": len(self.modules),
            "symbols": len(self.symbols),
            "imports": len(self.imports),
            "packages": len(self.packages),
            "calls": len(self.calls),
        }
