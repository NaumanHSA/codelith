"""
TypeScript and JavaScript support.

The second provider, and the first test of whether `LanguageProvider` is an
abstraction or just a claim. Nothing outside `app/languages/` changes to add it —
if anything had to, the seam leaked and that is the finding.

**No AST here, unlike Python.** There is no stdlib TypeScript parser, and shelling
out to Node would put a runtime dependency in the analysis path for a product whose
claim is that nothing leaves the machine. So this is a line scanner: it tracks brace
depth to know which class a method belongs to and where a declaration ends, and
matches declaration keywords at the start of a line.

**Comments and strings are blanked before anything is matched.** That is not a
refinement, it is the whole difference between working and not. The Python provider
shipped three detectors that matched the comments documenting them — `is_entrypoint`
found `__name__ == "__main__"` inside the comment explaining the idiom, and an
`os.getenv("X")` in a docstring became an environment variable called `X`. A regex
provider has no AST to fall back on, so it pays that tax up front: `_strip_noise`
replaces every comment and string literal with spaces, preserving line and column
positions so reported line numbers stay true.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from codelith.knowledge.constants import EntityKind
from codelith.languages.base import (
    CallRef,
    DetectedEntity,
    ImportRef,
    LanguageProvider,
    ModuleRef,
    Symbol,
)
from codelith.languages.taxonomy import ModuleKind, SymbolKind, Visibility

# ── Declarations ──────────────────────────────────────────────────────────────

_FUNCTION = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)")
_CLASS = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)")
_INTERFACE = re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)")
_TYPE_ALIAS = re.compile(r"^\s*(?:export\s+)?type\s+(\w+)\s*[=<]")
_ENUM = re.compile(r"^\s*(?:export\s+)?(?:const\s+)?enum\s+(\w+)")
_BINDING = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*(.*)$")

#: `(a, b) => `, `async (a) => `, `a => `, or a plain `function(` on the right of `=`.
_IS_CALLABLE_VALUE = re.compile(r"^(?:async\s+)?(?:\([^)]*\)|\w+)\s*(?::[^=]+)?=>|^(?:async\s+)?function\b")

#: A method inside a class body. Deliberately strict about what precedes the name,
#: because `if (x) {` and `for (const a of b) {` are the same shape otherwise.
_METHOD = re.compile(
    r"^\s*(?:(public|private|protected)\s+)?(?:static\s+)?(?:readonly\s+)?"
    r"(?:(?:async|get|set)\s+)?\*?\s*(#?\w+)\s*(?:<[^>]*>)?\s*\("
)
#: Declaration kinds whose body is a scope: they can contain other declarations,
#: and being inside one changes what counts as a symbol.
_OPENS_SCOPE = frozenset({
    SymbolKind.CLASS, SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.CONSTRUCTOR,
})

_NOT_A_METHOD = frozenset({
    "if", "for", "while", "switch", "catch", "return", "typeof", "await",
    "function", "constructor?", "do", "else", "new", "throw", "super",
})

# ── Imports ───────────────────────────────────────────────────────────────────

_IMPORT_FROM = re.compile(r"""^\s*import\s+(?:type\s+)?(.+?)\s+from\s+['"]([^'"]+)['"]""")
_IMPORT_BARE = re.compile(r"""^\s*import\s+['"]([^'"]+)['"]""")
_EXPORT_FROM = re.compile(r"""^\s*export\s+(?:\*|\{[^}]*\})\s+from\s+['"]([^'"]+)['"]""")
_REQUIRE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
_NAMED = re.compile(r"\{([^}]*)\}")

#: Extensions tried when resolving `./thing`, in the order a bundler would.
_RESOLVE_SUFFIXES = (
    ".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs",
    "/index.ts", "/index.tsx", "/index.js", "/index.jsx",
)

# ── Entities ──────────────────────────────────────────────────────────────────

_ENV_VAR = re.compile(r"(?:import\.meta\.env|process\.env)\.([A-Z][A-Z0-9_]*)")
_ENV_VAR_INDEXED = re.compile(r"""(?:import\.meta\.env|process\.env)\[\s*['"]([A-Z][A-Z0-9_]*)['"]""")
_ROUTE = re.compile(
    r"""\b(?:app|router|api|server)\.(get|post|put|patch|delete|all|use)\s*\(\s*['"]([^'"]+)['"]"""
)
_URL = re.compile(r"https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_PLACEHOLDER_HOSTS = ("example.com", "example.org", "example.net", "yourdomain.com")

_ENTRYPOINT_NAMES = frozenset({
    "main.ts", "main.tsx", "main.js", "main.jsx",
    "index.ts", "index.tsx", "index.js",
    "server.ts", "server.js", "app.ts", "app.js", "cli.ts", "cli.js",
})

#: `index.ts` is a re-export barrel in nearly every directory of a real project.
#: Only the ones near the root are plausibly a way *into* the system.
_MAX_ENTRYPOINT_DEPTH = 2

_CALL = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
_CALL_KEYWORDS = frozenset({
    "if", "for", "while", "switch", "catch", "return", "typeof", "function",
    "await", "new", "throw", "super", "import", "require", "constructor",
})


def _strip_noise(source: str) -> str:
    """
    Source with comments and string literals blanked, positions preserved.

    Every character removed is replaced by a space and newlines are kept, so line
    numbers and column offsets still describe the original file. Without this a
    regex provider reads its own documentation as code — the exact failure the
    Python provider shipped three times.
    """
    out = list(source)
    i, n = 0, len(source)
    state: str | None = None  # "line", "block", "'", '"', "`"

    def blank(index: int) -> None:
        if out[index] != "\n":
            out[index] = " "

    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

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
            if ch in "'\"`":
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

        # Inside a string literal.
        if ch == "\\":
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


class TypeScriptProvider(LanguageProvider):
    language = "typescript"
    display_name = "TypeScript"
    extensions = (".ts", ".tsx", ".mts", ".cts")
    manifest_files = ("package.json",)

    # ── Symbols ───────────────────────────────────────────────────────────────

    def extract_symbols(self, source: str, relative_path: str) -> list[Symbol]:
        """
        Declarations, excluding locals.

        A single scope stack does three jobs: it gives a method its class as
        `parent`, it closes a declaration's `end_line`, and it says whether we are
        inside a function body — which is what keeps `const box = ...` out of the
        index. Measured on the studio before that rule: 456 of 740 symbols were
        function-local `const`s. They are not API surface, they are noise that
        crowds the real declarations out of every summary and every retrieval.
        """
        lines = _strip_noise(source).split("\n")
        symbols: list[Symbol] = []
        #: (depth it opened at, name, is_class) — innermost last.
        scopes: list[tuple[int, str, bool]] = []
        depth = 0

        for index, line in enumerate(lines, start=1):
            if line.strip():
                symbol = self._declaration(line, index, scopes)
                if symbol is not None:
                    symbols.append(symbol)
                    if symbol.kind in _OPENS_SCOPE and "{" in line:
                        scopes.append((depth, symbol.name, symbol.kind is SymbolKind.CLASS))

            depth += line.count("{") - line.count("}")
            while scopes and depth <= scopes[-1][0]:
                _, name, _ = scopes.pop()
                for symbol in reversed(symbols):
                    if symbol.name == name and symbol.end_line is None:
                        symbol.end_line = index
                        break

        return symbols

    def _declaration(
        self, line: str, index: int, scopes: list[tuple[int, str, bool]]
    ) -> Symbol | None:
        class_stack = [s for s in scopes if s[2]]
        parent = class_stack[-1][1] if class_stack else None
        # Inside a function body, not a class body. Nested functions still count —
        # a React handler is real structure — but local bindings do not.
        in_function = any(not is_class for _, _, is_class in scopes)
        exported = bool(re.match(r"\s*export\b", line))

        if match := _CLASS.match(line):
            return self._symbol(match.group(1), SymbolKind.CLASS, index, exported, None, line)
        if match := _INTERFACE.match(line):
            return self._symbol(match.group(1), SymbolKind.INTERFACE, index, exported, parent, line)
        if match := _TYPE_ALIAS.match(line):
            return self._symbol(match.group(1), SymbolKind.TYPE_ALIAS, index, exported, parent, line)
        if match := _ENUM.match(line):
            return self._symbol(match.group(1), SymbolKind.ENUM, index, exported, parent, line)
        if match := _FUNCTION.match(line):
            kind = SymbolKind.METHOD if parent else SymbolKind.FUNCTION
            return self._symbol(match.group(1), kind, index, exported, parent, line)

        if match := _BINDING.match(line):
            name, value = match.group(2), match.group(3).strip()
            # `const handler = () => {}` is a function; `const MAX = 5` is a constant.
            if _IS_CALLABLE_VALUE.match(value):
                kind = SymbolKind.FUNCTION
            elif in_function:
                # A local. Not API surface, and 456 of the studio's 740 symbols
                # before this rule.
                return None
            elif name.isupper():
                kind = SymbolKind.CONSTANT
            else:
                kind = SymbolKind.FIELD if parent else SymbolKind.VARIABLE
            return self._symbol(name, kind, index, exported, parent, line)

        # Methods only inside a class body, or `if (…) {` becomes a method called `if`.
        if class_stack and not in_function and (match := _METHOD.match(line)):
            name = match.group(2)
            if name in _NOT_A_METHOD or not name:
                return None
            kind = SymbolKind.CONSTRUCTOR if name == "constructor" else SymbolKind.METHOD
            visibility = (
                Visibility.PRIVATE
                if match.group(1) == "private" or name.startswith("#")
                else Visibility.INTERNAL
                if match.group(1) == "protected"
                else self.visibility_of(name)
            )
            return Symbol(
                name=name.lstrip("#"),
                kind=kind,
                line=index,
                visibility=visibility,
                signature=line.strip()[:200],
                parent=parent,
            )
        return None

    def _symbol(
        self,
        name: str,
        kind: SymbolKind,
        line: int,
        exported: bool,
        parent: str | None,
        source_line: str,
    ) -> Symbol:
        return Symbol(
            name=name,
            kind=kind,
            line=line,
            # Export is the module boundary in this language: an unexported
            # declaration cannot be referenced from another file, whatever it is
            # named. So absence of `export` decides this, not the naming convention
            # `visibility_of` applies — which would have called every unexported
            # declaration public.
            visibility=Visibility.PUBLIC if exported else Visibility.INTERNAL,
            signature=source_line.strip()[:200],
            parent=parent,
        )

    def visibility_of(self, name: str) -> Visibility:
        return Visibility.INTERNAL if name.startswith("_") else Visibility.PUBLIC

    # ── Modules and files ─────────────────────────────────────────────────────

    def module_ref_for(self, relative_path: str) -> ModuleRef:
        p = PurePosixPath(relative_path)
        parent = p.parent.as_posix()
        if parent in ("", "."):
            return ModuleRef(key=p.stem, name=p.stem, kind=ModuleKind.FILE)
        return ModuleRef(key=parent, name=parent.replace("/", "."), kind=ModuleKind.PACKAGE)

    def is_test_file(self, relative_path: str) -> bool:
        p = PurePosixPath(relative_path)
        name = p.name.lower()
        if ".test." in name or ".spec." in name:
            return True
        return any(part in ("__tests__", "tests", "test", "e2e", "cypress") for part in p.parts)

    def is_entrypoint(self, relative_path: str, source: str) -> bool:
        p = PurePosixPath(relative_path)
        if self.is_test_file(relative_path):
            return False
        if p.name not in _ENTRYPOINT_NAMES:
            return False
        # `index.ts` is a re-export barrel in nearly every directory of a real
        # project. Counting all of them made "the ways into this system" meaningless.
        return relative_path.count("/") <= _MAX_ENTRYPOINT_DEPTH

    # ── Graph ─────────────────────────────────────────────────────────────────

    def extract_imports(self, source: str, relative_path: str) -> list[ImportRef]:
        refs: list[ImportRef] = []
        for index, line in enumerate(_strip_noise(source).split("\n"), start=1):
            # Blanked strings mean the *specifier* is gone too, so imports are read
            # from the original line — but only where the stripped line proves the
            # statement is real code rather than a comment or a string.
            if not line.strip():
                continue
            raw = source.split("\n")[index - 1]

            if match := _IMPORT_FROM.match(raw):
                refs.append(ImportRef(
                    target=match.group(2), line=index, names=_imported_names(match.group(1))
                ))
            elif match := _IMPORT_BARE.match(raw):
                refs.append(ImportRef(target=match.group(1), line=index))
            elif match := _EXPORT_FROM.match(raw):
                refs.append(ImportRef(target=match.group(1), line=index))
            for match in _REQUIRE.finditer(raw):
                refs.append(ImportRef(target=match.group(1), line=index))
        return refs

    def resolve_import(
        self, ref: ImportRef, from_path: str, known_files: frozenset[str]
    ) -> str | None:
        """
        A relative specifier resolved the way a bundler would.

        Only relative and rooted specifiers can be repository files. A bare
        specifier is a package — `react`, `@tanstack/query` — and inventing a file
        node for it would fill the graph with things that do not exist.
        """
        target = ref.target
        if not target.startswith("."):
            return None

        base = PurePosixPath(from_path).parent
        try:
            resolved = (base / target).as_posix()
        except ValueError:  # pragma: no cover - defensive
            return None
        # `a/b/../c` → `a/c`
        parts: list[str] = []
        for part in resolved.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        candidate = "/".join(parts)

        if candidate in known_files:
            return candidate
        for suffix in _RESOLVE_SUFFIXES:
            if (attempt := f"{candidate}{suffix}") in known_files:
                return attempt
        return None

    def external_package(self, ref: ImportRef) -> str | None:
        """
        The npm package a bare specifier belongs to.

        Scoped packages keep both segments: `@tanstack/react-query` is one package,
        and recording it as `@tanstack` would merge every unrelated library from
        that organisation into one node.
        """
        target = ref.target
        if not target or target.startswith("."):
            return None
        if target.startswith("@"):
            parts = target.split("/")
            return "/".join(parts[:2]) if len(parts) >= 2 else target
        return target.split("/")[0]

    def extract_calls(self, source: str, relative_path: str) -> list[CallRef]:
        """
        Call sites, attributed to the nearest preceding declaration.

        Cruder than the Python provider, which walks a real tree. The graph builder
        only keeps a call whose callee it can resolve to a symbol we recorded, so
        the imprecision costs recall rather than accuracy.
        """
        clean = _strip_noise(source).split("\n")
        symbols = self.extract_symbols(source, relative_path)
        callables = sorted(
            (s for s in symbols if s.kind in (
                SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.CONSTRUCTOR
            )),
            key=lambda s: s.line,
        )
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

        def record(kind: str, name: str, data: dict, line: int | None = None) -> None:
            if (str(kind), name) in seen:
                return
            seen.add((str(kind), name))
            found.append(DetectedEntity(kind=kind, name=name, data=data, line=line))

        # Env vars read off the *original* source: the name sits in an attribute or a
        # string, and the stripped copy has blanked one of them. Safe because the
        # pattern requires the `import.meta.env` / `process.env` prefix, which a
        # comment mentioning it in passing does not produce in this exact shape...
        # except it can. So each match is checked against the blanked copy: if the
        # prefix survived stripping, it was code.
        # Not from tests. A test sets whatever names it needs to exercise the loader,
        # and those names are not configuration the application requires. The same
        # reasoning already excludes tests from `is_entrypoint`.
        if not self.is_test_file(relative_path):
            for pattern in (_ENV_VAR, _ENV_VAR_INDEXED):
                for match in pattern.finditer(source):
                    if "env" in clean[match.start() : match.start() + 20]:
                        record(EntityKind.ENV_VAR, match.group(1), {}, _line_of(source, match.start()))

        for match in _ROUTE.finditer(source):
            if not clean[match.start() : match.start() + 6].strip():
                continue  # the whole expression was inside a comment or a string
            method, path = match.group(1).upper(), match.group(2)
            record(
                EntityKind.ROUTE,
                f"{method} {path}" if method != "USE" else path,
                {"method": None if method == "USE" else method, "path": path},
                _line_of(source, match.start()),
            )

        for match in _URL.finditer(source):
            host = match.group(1)
            if not host.endswith(_PLACEHOLDER_HOSTS):
                record(EntityKind.EXTERNAL_API, host, {"via": "url"}, _line_of(source, match.start()))

        if self.is_entrypoint(relative_path, source):
            record(EntityKind.ENTRYPOINT, relative_path, {"language": self.language})

        return found

    def parse_manifest(self, relative_path: str, source: str) -> list[DetectedEntity]:
        """Dependencies from `package.json`, runtime and dev alike."""
        import json

        if PurePosixPath(relative_path).name != "package.json":
            return []
        try:
            data = json.loads(source)
        except (json.JSONDecodeError, ValueError):
            return []

        out: list[DetectedEntity] = []
        for section, dev in (("dependencies", False), ("devDependencies", True)):
            for name, version in (data.get(section) or {}).items():
                out.append(DetectedEntity(
                    kind=EntityKind.DEPENDENCY,
                    name=str(name),
                    data={"version": str(version), "dev": dev, "ecosystem": "npm"},
                ))
        for name in (data.get("scripts") or {}):
            out.append(DetectedEntity(
                kind=EntityKind.CLI_COMMAND,
                name=f"npm run {name}",
                data={"source": "package.json"},
            ))
        return out


class JavaScriptProvider(TypeScriptProvider):
    """
    Same grammar, minus the types.

    A separate provider rather than more extensions on the one above, because
    `language` is persisted on every module and chunk — a project should be able to
    report that it is JavaScript rather than being told it is TypeScript.
    """

    language = "javascript"
    display_name = "JavaScript"
    extensions = (".js", ".jsx", ".mjs", ".cjs")


def _imported_names(clause: str) -> tuple[str, ...]:
    """`{ a, b as c }, Default` → the names this file can now call."""
    names: list[str] = []
    if match := _NAMED.search(clause):
        for part in match.group(1).split(","):
            piece = part.strip()
            if not piece:
                continue
            # `a as b` — the local name is what call sites use.
            names.append(piece.split(" as ")[-1].strip())
        clause = clause[: match.start()] + clause[match.end() :]
    for part in clause.split(","):
        piece = part.strip().removeprefix("* as ").strip()
        if piece and piece.isidentifier():
            names.append(piece)
    return tuple(dict.fromkeys(n for n in names if n))


def _line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


__all__ = ["TypeScriptProvider", "JavaScriptProvider"]
