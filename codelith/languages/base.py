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
class RunInfo:
    """
    What one manifest says about installing, running and testing the code, in terms
    every language shares. Commands are as run from the manifest's own folder.
    """

    #: "Python", "Node.js", "Go", "Java".
    runtime: str | None = None
    #: The version the manifest asks for, as written: `>=3.11`, `1.22`, `17`.
    version: str | None = None
    install: list[str] = field(default_factory=list)
    #: `(command, what it does)`.
    run: list[tuple[str, str]] = field(default_factory=list)
    test: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Issue:
    """
    A problem a provider found in one file, in terms every language shares.

    The QA app turns these into findings; this layer only says what is wrong, where,
    and why. `area` is one of `security`, `leakage`, `errors`, `breaks`,
    `performance`, `config`, `tests`; `severity` one of `critical`, `high`,
    `medium`, `low`, `info`; `confidence` `confirmed` for an exact pattern and
    `likely` for a heuristic that is usually right.
    """

    rule: str
    area: str
    severity: str
    line: int
    title: str
    #: Why it matters, in a sentence or two.
    message: str
    #: What to do about it.
    fix: str
    end_line: int | None = None
    confidence: str = "confirmed"


@dataclass(slots=True)
class Declared:
    """One dependency a manifest declares."""

    name: str
    #: The version asked for, as written; empty when none is.
    spec: str
    #: Only for development: tests, linting, docs.
    dev: bool
    line: int | None
    #: OSV's name for the ecosystem: `PyPI`, `npm`, `Go`, `Maven`.
    ecosystem: str


@dataclass(slots=True)
class Guards:
    """What requires a signed-in caller before a route's handler runs, in one file."""

    #: Handler qualname (`Class.*` for every method of a class) to what guards it.
    handlers: dict[str, str] = field(default_factory=dict)
    #: Router variable to what guards every route registered on it.
    routers: dict[str, str] = field(default_factory=dict)
    #: What guards every request to the app, when this file sets that up.
    app: str | None = None
    #: Type aliases that require a signed-in caller wherever a parameter uses them
    #: (`AdminUser = Annotated[User, Depends(get_current_admin)]`), to what they wrap.
    aliases: dict[str, str] = field(default_factory=dict)
    #: Handler qualname to the type names its parameters use, for the aliases above,
    #: which are usually declared in another file.
    uses: dict[str, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class Sink:
    """A call that does something dangerous with a value its function was handed."""

    #: `sql`, `shell`, `code`, `file`, `url`, `log` or `deserialize`.
    kind: str
    line: int
    #: The enclosing function's qualname.
    function: str
    #: That function's parameters whose values reach the call.
    params: list[str]
    call: str


@dataclass(slots=True)
class FlowFacts:
    """What QA needs from one file to follow a request through it."""

    guards: Guards = field(default_factory=Guards)
    sinks: list[Sink] = field(default_factory=list)
    #: Names of the models routes in this file answer with.
    response_models: set[str] = field(default_factory=set)
    #: Data models declared here: name to `(field, line)`.
    models: dict[str, list[tuple[str, int]]] = field(default_factory=dict)


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
    #: Files recording the exact versions the manifests resolved to. Kept with the
    #: reading for comparison and for the dependency audit; never parsed for facts.
    lock_files: tuple[str, ...] = ()
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

    def inspect(self, relative_path: str, source: str) -> list[Issue]:
        """
        Problems in one file: injection, swallowed errors, blocking calls in async code
        and the rest, as this language writes them. Default is none, which QA reports
        as "no rules for this language" rather than as a clean file.
        """
        return []

    #: Whether `inspect` has rules at all, so QA can say a language went unchecked.
    has_rules: bool = False
    #: Each rule's short name, the same for every finding of it: how findings are
    #: grouped, and what a report lists the rule as.
    qa_rules: dict[str, str] = {}

    def flow_facts(self, relative_path: str, source: str) -> FlowFacts | None:
        """
        Guards, sinks and response models in one file, for following requests through
        the recorded calls. `None` when this language cannot say, which QA reports.
        """
        return None

    # -- Dependencies, for QA's audit -------------------------------------------------

    #: OSV's name for this language's package ecosystem, when it has one.
    ecosystem: str | None = None

    def declared(self, relative_path: str, source: str) -> list[Declared]:
        """What one of `manifest_files` declares, with the version asked for."""
        return []

    def locked(self, relative_path: str, source: str) -> dict[str, str]:
        """What one of `lock_files` pins: normalised package name to version."""
        return {}

    def imported_packages(self, relative_path: str, source: str) -> list[tuple[str, int]]:
        """`(package, line)` for the outside packages a source file imports: not the
        language's own library. Local modules are told apart by QA, which sees them all."""
        return []

    def normalise_package(self, name: str) -> str:
        return name

    def provides(self, package: str, imported: str) -> bool:
        """Whether a declared package is what an import name comes from."""
        return self.normalise_package(package) == self.normalise_package(imported)

    def never_imported(self, package: str) -> bool:
        """A package installed to be run or loaded by name: never "unused"."""
        return False

    def syntax_needs(self, relative_path: str, source: str) -> list[tuple[str, str, int]]:
        """`(feature, minimum version, line)` for syntax newer than it looks."""
        return []

    def run_info(self, relative_path: str, source: str, siblings: frozenset[str]) -> RunInfo | None:
        """
        What one of `manifest_files` says about installing, running and testing the
        code. `siblings` are the names of the files beside it, which decide things
        like the package manager (a `pnpm-lock.yaml` means pnpm). Default is nothing.
        """
        return None

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

    def resolve_import_all(
        self, ref: ImportRef, from_path: str, known_files: frozenset[str]
    ) -> list[str]:
        """
        Every repository file one import statement brings in, the file `resolve_import`
        finds first. Most languages import one file per statement, which is the default;
        a provider whose statements can name several modules at once (Python's
        `from pkg import a, b`, where `a` and `b` are files) adds them, or the files those
        modules live in would seem to have no importers.
        """
        target = self.resolve_import(ref, from_path, known_files)
        return [target] if target else []

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
    "Declared",
    "FlowFacts",
    "Guards",
    "Issue",
    "Sink",
    "RunInfo",
    "LanguageProvider",
    "Symbol",
    "ModuleRef",
    "DetectedEntity",
    "ImportRef",
    "CallRef",
]
