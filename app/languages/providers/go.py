"""
Go support.

Third provider, and the first written against the conformance suite rather than
against a reading of the interface. Everything it must satisfy was fixed before a
line of it existed, which is the point of having the suite.

Go is unusually kind to a line scanner: declarations are at column zero, the
visibility rule is a single character, and packages are directories. The two things
that need care are the grouped `import (...)` block, and resolving a module path like
`github.com/acme/widget/internal/helpers` onto a directory in the repository — the
module prefix is not knowable from the import alone, so it is matched by suffix
against files that actually exist.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from app.knowledge.constants import EntityKind
from app.languages.base import (
    CallRef,
    DetectedEntity,
    ImportRef,
    LanguageProvider,
    ModuleRef,
    Symbol,
)
from app.languages.taxonomy import ModuleKind, SymbolKind, Visibility

_FUNC = re.compile(r"^func\s+(\w+)\s*(?:\[[^\]]*\])?\s*\(")
#: `func (s *UserService) Fetch(` — the receiver names the method's container.
_METHOD = re.compile(r"^func\s+\(\s*\w+\s+\*?(\w+)\s*\)\s*(\w+)\s*(?:\[[^\]]*\])?\s*\(")
_TYPE = re.compile(r"^type\s+(\w+)\s+(struct|interface)\b")
_TYPE_ALIAS = re.compile(r"^type\s+(\w+)\s+(?!struct\b|interface\b)\S+")
#: Top-level `const X = …` / `var X = …`, and entries inside a `const (…)` group.
_CONST_VAR = re.compile(r"^(const|var)\s+(\w+)")
_GROUP_ENTRY = re.compile(r"^\s+(\w+)\s*(?:[\w\[\]*.]+\s*)?=")

_IMPORT_SINGLE = re.compile(r"""^import\s+(?:\w+\s+)?["']([^"']+)["']""")
_IMPORT_GROUP_ENTRY = re.compile(r"""^\s*(?:[\w.]+\s+)?["']([^"']+)["']""")

_ENV_VAR = re.compile(r"""os\.(?:Getenv|LookupEnv)\(\s*["']([A-Z][A-Z0-9_]*)["']""")
#: gin/echo/chi style routing, plus the stdlib mux.
_ROUTE = re.compile(
    r"""\b\w+\.(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|Handle|HandleFunc)\(\s*["']([^"']+)["']"""
)
_URL = re.compile(r"https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)([A-Za-z0-9.-]+\.[A-Za-z]{2,})")

_REQUIRE_LINE = re.compile(r"^\s*(?:require\s+)?([\w.\-]+\.[\w.\-]+/[^\s]+)\s+v[\w.\-+]+")

_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_CALL_KEYWORDS = frozenset({
    "if", "for", "switch", "return", "func", "go", "defer", "make", "new",
    "len", "cap", "append", "range", "select", "panic", "recover", "print",
})


def _strip_noise(source: str) -> str:
    """
    Comments and string literals blanked, positions preserved.

    Same tax the TypeScript provider pays and for the same reason: without it a
    scanner reads the comment documenting a declaration as the declaration. Go's raw
    strings use backticks and may span lines, which is why this is a scanner rather
    than a line-wise regex.
    """
    out = list(source)
    i, n = 0, len(source)
    state: str | None = None

    def blank(index: int) -> None:
        if out[index] != "\n":
            out[index] = " "

    while i < n:
        ch, nxt = source[i], source[i + 1] if i + 1 < n else ""

        if state is None:
            if ch == "/" and nxt == "/":
                state = "line"
                blank(i)
                blank(i + 1)
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block"
                blank(i)
                blank(i + 1)
                i += 2
                continue
            if ch in "\"'`":
                state = ch
                blank(i)
            i += 1
            continue

        if state == "line":
            if ch == "\n":
                state = None
            else:
                blank(i)
            i += 1
            continue

        if state == "block":
            if ch == "*" and nxt == "/":
                blank(i)
                blank(i + 1)
                state = None
                i += 2
                continue
            blank(i)
            i += 1
            continue

        # Inside a string. Backtick strings have no escapes.
        if ch == "\\" and state != "`":
            blank(i)
            if i + 1 < n:
                blank(i + 1)
            i += 2
            continue
        if ch == state:
            state = None
        blank(i)
        i += 1

    return "".join(out)


class GoProvider(LanguageProvider):
    language = "go"
    display_name = "Go"
    extensions = (".go",)
    manifest_files = ("go.mod",)

    # ── Symbols ───────────────────────────────────────────────────────────────

    def extract_symbols(self, source: str, relative_path: str) -> list[Symbol]:
        """
        Top-level declarations only.

        Go puts every declaration at column zero, so indentation alone separates API
        surface from function bodies — `localBinding := …` is indented and therefore
        never seen. The one exception is a grouped `const (…)` block, whose entries
        are indented but are genuinely package-level.
        """
        lines = _strip_noise(source).split("\n")
        symbols: list[Symbol] = []
        in_group: str | None = None
        depth = 0

        for index, line in enumerate(lines, start=1):
            if in_group is not None:
                if line.strip().startswith(")"):
                    in_group = None
                elif match := _GROUP_ENTRY.match(line):
                    symbols.append(self._symbol(match.group(1), _KIND[in_group], index, line))
                depth += line.count("{") - line.count("}")
                continue

            if re.match(r"^(const|var)\s*\($", line.strip()):
                in_group = line.strip().split("(")[0].strip()
                continue

            # Column zero only — anything indented is inside a body.
            if line[:1] not in ("", " ", "\t"):
                if match := _METHOD.match(line):
                    symbols.append(Symbol(
                        name=match.group(2),
                        kind=SymbolKind.METHOD,
                        line=index,
                        visibility=self.visibility_of(match.group(2)),
                        signature=line.strip()[:200],
                        parent=match.group(1),
                    ))
                elif match := _FUNC.match(line):
                    symbols.append(self._symbol(match.group(1), SymbolKind.FUNCTION, index, line))
                elif match := _TYPE.match(line):
                    kind = (
                        SymbolKind.STRUCT if match.group(2) == "struct" else SymbolKind.INTERFACE
                    )
                    symbols.append(self._symbol(match.group(1), kind, index, line))
                elif match := _TYPE_ALIAS.match(line):
                    symbols.append(
                        self._symbol(match.group(1), SymbolKind.TYPE_ALIAS, index, line)
                    )
                elif match := _CONST_VAR.match(line):
                    symbols.append(self._symbol(match.group(2), _KIND[match.group(1)], index, line))

            depth += line.count("{") - line.count("}")

        return symbols

    def _symbol(self, name: str, kind: SymbolKind, line: int, source_line: str) -> Symbol:
        return Symbol(
            name=name,
            kind=kind,
            line=line,
            visibility=self.visibility_of(name),
            signature=source_line.strip()[:200],
        )

    def visibility_of(self, name: str) -> Visibility:
        """
        A capital letter is the entire export rule in this language.

        No keyword, no convention — `Fetch` is reachable from another package and
        `fetch` is not.
        """
        return Visibility.PUBLIC if name[:1].isupper() else Visibility.INTERNAL

    # ── Files ─────────────────────────────────────────────────────────────────

    def module_ref_for(self, relative_path: str) -> ModuleRef:
        """A Go package is a directory, which is what the default already assumes."""
        parent = PurePosixPath(relative_path).parent.as_posix()
        if parent in ("", "."):
            return ModuleRef(key=".", name="main", kind=ModuleKind.PACKAGE)
        return ModuleRef(key=parent, name=parent.replace("/", "."), kind=ModuleKind.PACKAGE)

    def is_test_file(self, relative_path: str) -> bool:
        return PurePosixPath(relative_path).name.endswith("_test.go")

    def is_entrypoint(self, relative_path: str, source: str) -> bool:
        if self.is_test_file(relative_path):
            return False
        if PurePosixPath(relative_path).name != "main.go":
            return False
        # `package main` with no `func main` is a library that happens to be named
        # badly; an empty source is trusted, since callers sometimes have only a path.
        if not source.strip():
            return True
        clean = _strip_noise(source)
        return "package main" in clean and re.search(r"^func\s+main\s*\(", clean, re.M) is not None

    # ── Graph ─────────────────────────────────────────────────────────────────

    def extract_imports(self, source: str, relative_path: str) -> list[ImportRef]:
        refs: list[ImportRef] = []
        clean = _strip_noise(source).split("\n")
        raw = source.split("\n")
        in_block = False

        for index, line in enumerate(clean, start=1):
            original = raw[index - 1] if index - 1 < len(raw) else ""
            stripped = line.strip()

            if in_block:
                if stripped.startswith(")"):
                    in_block = False
                elif match := _IMPORT_GROUP_ENTRY.match(original):
                    refs.append(ImportRef(target=match.group(1), line=index))
                continue

            if stripped.startswith("import ("):
                in_block = True
                continue
            if stripped.startswith("import") and (match := _IMPORT_SINGLE.match(original.strip())):
                refs.append(ImportRef(target=match.group(1), line=index))

        return refs

    def resolve_import(
        self, ref: ImportRef, from_path: str, known_files: frozenset[str]
    ) -> str | None:
        """
        A module path onto a directory that exists here.

        `github.com/acme/widget/internal/helpers` carries a module prefix that is
        declared in `go.mod` and is not knowable from the import alone. Rather than
        parse it, progressively shorter suffixes are tried against directories we can
        see — the longest match that contains Go files wins, so a coincidental short
        suffix cannot beat the real one.
        """
        if not ref.target or "/" not in ref.target:
            return None

        segments = ref.target.split("/")
        for start in range(len(segments)):
            directory = "/".join(segments[start:])
            candidates = sorted(
                path
                for path in known_files
                if path.endswith(".go")
                and path.startswith(f"{directory}/")
                and "/" not in path[len(directory) + 1 :]
            )
            if candidates:
                # A package is many files; the graph edge points at one of them, so
                # pick deterministically rather than by iteration order.
                return candidates[0]
        return None

    def external_package(self, ref: ImportRef) -> str | None:
        """
        The module a non-repository import belongs to.

        Go's standard library never has a dot in its first segment — `os`, `fmt`,
        `net/http` — and a third-party module path always begins with a host. That
        one rule separates them exactly, with no list to maintain.
        """
        target = ref.target
        if not target:
            return None
        head = target.split("/")[0]
        if "." not in head:
            return None
        # host/org/repo is the module; anything deeper is a package inside it.
        return "/".join(target.split("/")[:3])

    def extract_calls(self, source: str, relative_path: str) -> list[CallRef]:
        clean = _strip_noise(source).split("\n")
        callables = [
            s for s in self.extract_symbols(source, relative_path)
            if s.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD)
        ]
        if not callables:
            return []

        calls: list[CallRef] = []
        for index, line in enumerate(clean, start=1):
            enclosing = None
            for symbol in callables:
                if symbol.line <= index:
                    enclosing = symbol
                else:
                    break
            if enclosing is None:
                continue
            for match in _CALL.finditer(line):
                name = match.group(1)
                if name in _CALL_KEYWORDS or name == enclosing.name:
                    continue
                calls.append(CallRef(caller=enclosing.qualified_name, callee=name, line=index))
        return calls

    # ── Entities ──────────────────────────────────────────────────────────────

    def detect_entities(
        self, relative_path: str, source: str, symbols: list[Symbol]
    ) -> list[DetectedEntity]:
        clean = _strip_noise(source)
        found: list[DetectedEntity] = []
        seen: set[tuple[str, str]] = set()

        def record(kind, name: str, data: dict, line: int | None = None) -> None:
            if (str(kind), name) in seen:
                return
            seen.add((str(kind), name))
            found.append(DetectedEntity(kind=kind, name=name, data=data, line=line))

        # Matched against the *original* source because the name lives inside a
        # string literal, which stripping blanks — then checked against the stripped
        # copy, so a call written inside a comment does not count.
        # Not from tests. A test sets whatever names it needs to exercise the loader,
        # and those names are not configuration the application requires. The same
        # reasoning already excludes tests from `is_entrypoint`.
        if not self.is_test_file(relative_path):
            for match in _ENV_VAR.finditer(source):
                if clean[match.start() : match.start() + 3].strip():
                    record(EntityKind.ENV_VAR, match.group(1), {}, _line_of(source, match.start()))

        for match in _ROUTE.finditer(source):
            if not clean[match.start() : match.start() + 3].strip():
                continue
            method, path = match.group(1).upper(), match.group(2)
            if not path.startswith("/"):
                continue
            record(
                EntityKind.ROUTE,
                f"{method} {path}" if method not in ("HANDLE", "HANDLEFUNC") else path,
                {"method": None if method.startswith("HANDLE") else method, "path": path},
                _line_of(source, match.start()),
            )

        for match in _URL.finditer(source):
            if clean[match.start() : match.start() + 3].strip():
                record(
                    EntityKind.EXTERNAL_API, match.group(1), {"via": "url"},
                    _line_of(source, match.start()),
                )

        if self.is_entrypoint(relative_path, source):
            record(EntityKind.ENTRYPOINT, relative_path, {"language": self.language})

        return found

    def parse_manifest(self, relative_path: str, source: str) -> list[DetectedEntity]:
        """Modules required by `go.mod`, single-line or grouped."""
        if PurePosixPath(relative_path).name != "go.mod":
            return []

        out: list[DetectedEntity] = []
        seen: set[str] = set()
        for line in source.split("\n"):
            if line.strip().startswith("module "):
                continue
            if match := _REQUIRE_LINE.match(line):
                name = match.group(1)
                if name not in seen:
                    seen.add(name)
                    out.append(DetectedEntity(
                        kind=EntityKind.DEPENDENCY,
                        name=name,
                        data={"ecosystem": "go"},
                    ))
        return out


#: `const`/`var` keyword to the kind it declares.
_KIND = {"const": SymbolKind.CONSTANT, "var": SymbolKind.VARIABLE}


def _line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


__all__ = ["GoProvider"]
