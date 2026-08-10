"""
The contract every language implementation satisfies.

Adding a language means writing one `LanguageProvider` subclass and registering it —
no `if language == ...` branch anywhere else in the codebase. Everything that varies
between languages lives behind this interface:

  * which files belong to the language          → `extensions`
  * what a declaration looks like               → `extract_symbols`
  * how files group into a module               → `module_ref_for`
  * what counts as a test / entrypoint          → `is_test_file` / `is_entrypoint`
  * where dependencies are declared             → `manifest_files`
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from codelith.languages.taxonomy import ModuleKind, SymbolKind, Visibility


@dataclass(slots=True)
class Symbol:
    """One declaration found in a source file."""

    name: str
    kind: SymbolKind
    line: int
    end_line: int | None = None
    visibility: Visibility = Visibility.PUBLIC
    signature: str | None = None
    docstring: str | None = None
    parent: str | None = None          # enclosing class/namespace, if any
    decorators: list[str] = field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        return f"{self.parent}.{self.name}" if self.parent else self.name

    def to_dict(self) -> dict:
        """Serialised into `kb_modules.symbols_json` — keep keys stable."""
        data = {
            "name": self.name,
            "kind": str(self.kind),
            "line": self.line,
            "visibility": str(self.visibility),
        }
        if self.end_line is not None:
            data["end_line"] = self.end_line
        if self.signature:
            data["signature"] = self.signature
        if self.docstring:
            data["docstring"] = self.docstring
        if self.parent:
            data["parent"] = self.parent
        if self.decorators:
            data["decorators"] = self.decorators
        return data


@dataclass(slots=True)
class DetectedEntity:
    """
    A discrete fact a provider spotted in source — a route, an env var, an
    entrypoint, a dependency.

    `kind` is a plain string rather than an import of `app.knowledge.EntityKind`,
    so the language layer stays independent of the knowledge layer. Providers should
    use the `EntityKind` values; the extractor validates them.
    """

    kind: str
    name: str
    data: dict = field(default_factory=dict)
    line: int | None = None


@dataclass(slots=True, frozen=True)
class ImportRef:
    """
    One import, as written in the source.

    Deliberately unresolved: the text `from .. import session` means nothing without
    knowing the language's resolution rules and the file it appeared in. `resolve_import`
    turns this into a path, and only a provider can do that.
    """

    target: str
    line: int
    #: Names pulled in by a `from X import a, b`, so a call site can be traced back
    #: to the file that defines it.
    names: tuple[str, ...] = ()
    #: Relative-import depth. 0 is absolute; Python's `from ..pkg import x` is 2.
    level: int = 0


@dataclass(slots=True, frozen=True)
class CallRef:
    """
    A call site, named but not resolved.

    `callee` is the expression as written — `session.commit`, `build_modules`. Turning
    that into a symbol is the graph builder's job, and it is allowed to fail: a call
    it cannot resolve is dropped rather than guessed.
    """

    caller: str
    callee: str
    line: int


@dataclass(slots=True, frozen=True)
class ModuleRef:
    """
    Which module a file belongs to.

    `key` is the stable identifier stored on `kb_modules.path`; `name` is what a
    human (and the writer) should see.
    """

    key: str
    name: str
    kind: ModuleKind = ModuleKind.PACKAGE


class LanguageProvider(ABC):
    """Base class for per-language support. Subclasses must be stateless."""

    #: Canonical identifier persisted in the DB (e.g. "python"). Never rename.
    language: str = "unknown"
    #: Human-facing name.
    display_name: str = "Unknown"
    #: File extensions owned by this language, lowercase and dot-prefixed.
    extensions: tuple[str, ...] = ()
    #: Dependency/manifest files worth reading during analysis.
    manifest_files: tuple[str, ...] = ()
    #: Directories to skip *in addition to* the shared defaults in the registry.
    extra_ignored_dirs: frozenset[str] = frozenset()

    # ── Required ──────────────────────────────────────────────────────────────

    @abstractmethod
    def extract_symbols(self, source: str, relative_path: str) -> list[Symbol]:
        """Return declarations found in `source`. Must never raise on bad input."""

    # ── Overridable defaults ──────────────────────────────────────────────────

    def module_ref_for(self, relative_path: str) -> ModuleRef:
        """
        Group a file into a module. The default treats the containing directory as
        the module, which is right for most languages; override where it isn't.
        """
        p = PurePosixPath(relative_path)
        parent = p.parent.as_posix()
        if parent in ("", "."):
            return ModuleRef(key=p.stem, name=p.stem, kind=ModuleKind.FILE)
        return ModuleRef(key=parent, name=parent.replace("/", "."), kind=ModuleKind.PACKAGE)

    def is_test_file(self, relative_path: str) -> bool:
        lowered = relative_path.lower()
        return (
            "/test" in f"/{lowered}"
            or lowered.startswith("test")
            or "_test." in lowered
            or ".test." in lowered
            or ".spec." in lowered
        )

    def is_entrypoint(self, relative_path: str, source: str) -> bool:
        return False

    def visibility_of(self, name: str) -> Visibility:
        return Visibility.PUBLIC

    def detect_entities(
        self, relative_path: str, source: str, symbols: list[Symbol]
    ) -> list[DetectedEntity]:
        """
        Facts worth recording that need language knowledge to spot — HTTP routes
        from a decorator or annotation, environment variables from a config call.

        Default is none, so a provider can ship without this and still be useful.
        """
        return []

    def parse_manifest(self, relative_path: str, source: str) -> list[DetectedEntity]:
        """
        Declared dependencies from one of `manifest_files`. Default is none.
        """
        return []

    # ── Graph ─────────────────────────────────────────────────────────────────
    #
    # "What imports what" is a traversal, not a similarity, so vector search cannot
    # answer it. These three feed the code graph. All are optional: a provider that
    # implements none still produces a usable knowledge base, just without edges.

    def extract_imports(self, source: str, relative_path: str) -> list[ImportRef]:
        """Imports as written. Must never raise on bad input."""
        return []

    def resolve_import(
        self, ref: ImportRef, from_path: str, known_files: frozenset[str]
    ) -> str | None:
        """
        The repository file an import refers to, or `None` if it is external.

        `known_files` is every path in the repo, so resolution can be checked rather
        than guessed — a target that does not correspond to a real file is external
        (a third-party package) or unresolvable, and both must return `None`.
        Returning a path that is not in `known_files` is a bug: it invents a node.
        """
        return None

    def external_package(self, ref: ImportRef) -> str | None:
        """
        The third-party distribution an unresolved import belongs to, or `None`.

        Called only for imports `resolve_import` could not place inside the
        repository. Returning `None` drops the edge, which is what should happen for
        the standard library: `DEPENDS_ON typing` is not a dependency, and on a real
        repository stdlib imports outnumber real ones several times over.
        """
        return None

    def extract_calls(self, source: str, relative_path: str) -> list[CallRef]:
        """
        Call sites, named but unresolved. Must never raise on bad input.

        Approximate by nature in a dynamic language. Consumers are expected to treat
        `CALLS` edges as "might reach" rather than as a complete call graph.
        """
        return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def owns(self, relative_path: str) -> bool:
        return PurePosixPath(relative_path).suffix.lower() in self.extensions

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} language={self.language!r}>"


__all__ = [
    "LanguageProvider",
    "Symbol",
    "ModuleRef",
    "DetectedEntity",
    "ImportRef",
    "CallRef",
]
