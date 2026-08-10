"""
Java support.

Fourth provider, written against the conformance suite like Go was.

Java's structure is the friendliest of the four to a scanner, because brace depth
alone says what a declaration *is*: depth 0 is a type, depth 1 is a member of that
type, and depth 2 or more is a local. That one rule replaces the heuristics the
TypeScript provider needs, and it is why `int localBinding = …` never reaches the
index while `private String token;` does.

Imports are exact, unlike Go's: `com.acme.helpers.Helpers` maps onto
`com/acme/helpers/Helpers.java` with no module prefix to guess at. The only wrinkle
is the `src/main/java` prefix convention, which is matched by suffix so a project
using a different layout still resolves.
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

_TYPE_DECL = re.compile(
    r"^\s*(?:(public|private|protected)\s+)?(?:(?:static|final|abstract|sealed|non-sealed)\s+)*"
    r"(class|interface|enum|record|@interface)\s+(\w+)"
)
#: A member: modifiers, an optional generic return type, a name, then `(` or `=` or `;`.
_MEMBER = re.compile(
    r"^\s*(?:@\w+\s+)*(?:(public|private|protected)\s+)?"
    r"(?:(?:static|final|abstract|synchronized|native|transient|volatile|default)\s+)*"
    r"(?:<[^>]+>\s+)?"
    r"(?:[\w.$]+(?:<[^;{()]*>)?(?:\[\])*\s+)?"
    r"(\w+)\s*(\(|=|;)"
)
_NOT_A_MEMBER = frozenset({
    "if", "for", "while", "switch", "catch", "return", "new", "throw", "else",
    "do", "try", "finally", "synchronized", "assert", "super", "this",
})

_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;")
_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.$]+(?:\.\*)?)\s*;")

_ENV_VAR = re.compile(r"""System\.getenv\(\s*["']([A-Z][A-Z0-9_]*)["']""")
_ROUTE = re.compile(
    r"""@(?:Get|Post|Put|Patch|Delete|Request)Mapping\(\s*(?:value\s*=\s*)?["']([^"']+)["']"""
)
_URL = re.compile(r"https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)([A-Za-z0-9.-]+\.[A-Za-z]{2,})")

_POM_DEPENDENCY = re.compile(
    r"<groupId>\s*([^<\s]+)\s*</groupId>\s*<artifactId>\s*([^<\s]+)\s*</artifactId>", re.S
)
_GRADLE_DEPENDENCY = re.compile(
    r"""^\s*(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\s*"""
    r"""\(?\s*['"]([^'":]+):([^'":]+)(?::[^'"]*)?['"]"""
)

#: Package roots that ship with the JDK. Everything else is a dependency.
_STDLIB_ROOTS = ("java", "javax", "jdk", "sun", "com.sun")

_ENTRYPOINT_NAMES = frozenset({"Application.java", "Main.java", "App.java"})
_MAIN_METHOD = re.compile(r"public\s+static\s+void\s+main\s*\(")

#: Source roots stripped from a module name, so a package reads `com.acme.service`
#: rather than `src.main.java.com.acme.service`.
_SOURCE_ROOTS = ("src/main/java/", "src/test/java/", "src/main/kotlin/", "src/", "java/")

_CALL = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
_CALL_KEYWORDS = frozenset({
    "if", "for", "while", "switch", "catch", "return", "new", "throw",
    "super", "this", "synchronized", "assert",
})


def _strip_noise(source: str) -> str:
    """Comments and string literals blanked, positions preserved. See the TypeScript
    provider for why this is load-bearing rather than a nicety."""
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
            if ch in "\"'":
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


class JavaProvider(LanguageProvider):
    language = "java"
    display_name = "Java"
    extensions = (".java",)
    manifest_files = ("pom.xml", "build.gradle", "build.gradle.kts")

    # ── Symbols ───────────────────────────────────────────────────────────────

    def extract_symbols(self, source: str, relative_path: str) -> list[Symbol]:
        """
        Types and their members, never locals.

        Brace depth is the whole rule: a declaration at depth 0 is a type, at depth 1
        a member of the enclosing type, and at depth 2 or deeper a local variable
        inside a method body. No other language here separates them so cleanly.
        """
        lines = _strip_noise(source).split("\n")
        symbols: list[Symbol] = []
        #: (depth it opened at, type name) — innermost last, for nested classes.
        types: list[tuple[int, str]] = []
        depth = 0

        for index, line in enumerate(lines, start=1):
            if line.strip():
                if depth == 0 and (match := _TYPE_DECL.match(line)):
                    name = match.group(3)
                    symbols.append(Symbol(
                        name=name,
                        kind=_TYPE_KINDS.get(match.group(2), SymbolKind.CLASS),
                        line=index,
                        visibility=_visibility(match.group(1)),
                        signature=line.strip()[:200],
                        parent=types[-1][1] if types else None,
                    ))
                    if "{" in line:
                        types.append((depth, name))

                elif depth == 1 and types and (match := _MEMBER.match(line)):
                    name, terminator = match.group(2), match.group(3)
                    if name not in _NOT_A_MEMBER:
                        kind = (
                            SymbolKind.CONSTRUCTOR
                            if terminator == "(" and name == types[-1][1]
                            else SymbolKind.METHOD
                            if terminator == "("
                            else SymbolKind.FIELD
                        )
                        symbols.append(Symbol(
                            name=name,
                            kind=kind,
                            line=index,
                            visibility=_visibility(match.group(1)),
                            signature=line.strip()[:200],
                            parent=types[-1][1],
                        ))

            depth += line.count("{") - line.count("}")
            while types and depth <= types[-1][0]:
                _, name = types.pop()
                for symbol in reversed(symbols):
                    if symbol.name == name and symbol.end_line is None:
                        symbol.end_line = index
                        break

        return symbols

    def visibility_of(self, name: str) -> Visibility:
        """Java marks visibility with a keyword, so a name says nothing on its own."""
        return Visibility.PUBLIC

    # ── Files ─────────────────────────────────────────────────────────────────

    def module_ref_for(self, relative_path: str) -> ModuleRef:
        path = PurePosixPath(relative_path)
        parent = path.parent.as_posix()
        if parent in ("", "."):
            return ModuleRef(key=path.stem, name=path.stem, kind=ModuleKind.FILE)

        # `src/main/java/com/acme/service` reads as `com.acme.service`. The key stays
        # the real directory, because that is what every other layer joins on.
        name = parent
        for root in _SOURCE_ROOTS:
            if name.startswith(root):
                name = name[len(root) :]
                break
        return ModuleRef(
            key=parent,
            name=(name or parent).replace("/", "."),
            kind=ModuleKind.PACKAGE,
        )

    def is_test_file(self, relative_path: str) -> bool:
        path = PurePosixPath(relative_path)
        if path.stem.endswith(("Test", "Tests", "IT", "TestCase")):
            return True
        return "src/test" in relative_path or "test" in {p.lower() for p in path.parts[:-1]}

    def is_entrypoint(self, relative_path: str, source: str) -> bool:
        if self.is_test_file(relative_path):
            return False
        if PurePosixPath(relative_path).name in _ENTRYPOINT_NAMES:
            return True
        return bool(source) and _MAIN_METHOD.search(_strip_noise(source)) is not None

    # ── Graph ─────────────────────────────────────────────────────────────────

    def extract_imports(self, source: str, relative_path: str) -> list[ImportRef]:
        refs: list[ImportRef] = []
        for index, line in enumerate(_strip_noise(source).split("\n"), start=1):
            if match := _IMPORT.match(line):
                target = match.group(1)
                # `import com.acme.helpers.Helpers` brings in the last segment.
                names = () if target.endswith(".*") else (target.rsplit(".", 1)[-1],)
                refs.append(ImportRef(target=target, line=index, names=names))
        return refs

    def resolve_import(
        self, ref: ImportRef, from_path: str, known_files: frozenset[str]
    ) -> str | None:
        """
        A fully-qualified name onto the file that declares it.

        Exact, unlike Go: the package path is the directory path. Matched by suffix
        so the `src/main/java` convention is handled without being required.
        """
        target = ref.target
        if not target or target.endswith(".*"):
            return None

        suffix = target.replace(".", "/") + ".java"
        candidates = sorted(
            path for path in known_files if path == suffix or path.endswith(f"/{suffix}")
        )
        return candidates[0] if candidates else None

    def external_package(self, ref: ImportRef) -> str | None:
        """
        The library a non-repository import belongs to.

        Two segments: `org.springframework.stereotype.Service` is the Spring
        framework, and recording the full path would make every class its own
        dependency.
        """
        target = ref.target
        if not target:
            return None
        if target.startswith(_STDLIB_ROOTS):
            return None
        segments = target.split(".")
        return ".".join(segments[:2]) if len(segments) >= 2 else target

    def extract_calls(self, source: str, relative_path: str) -> list[CallRef]:
        clean = _strip_noise(source).split("\n")
        callables = [
            s for s in self.extract_symbols(source, relative_path)
            if s.kind in (SymbolKind.METHOD, SymbolKind.CONSTRUCTOR)
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

        # Not from tests. A test sets whatever names it needs to exercise the loader,
        # and those names are not configuration the application requires. The same
        # reasoning already excludes tests from `is_entrypoint`.
        if not self.is_test_file(relative_path):
            for match in _ENV_VAR.finditer(source):
                if clean[match.start() : match.start() + 6].strip():
                    record(EntityKind.ENV_VAR, match.group(1), {}, _line_of(source, match.start()))

        for match in _ROUTE.finditer(source):
            if clean[match.start() : match.start() + 4].strip():
                record(
                    EntityKind.ROUTE, match.group(1), {"path": match.group(1)},
                    _line_of(source, match.start()),
                )

        for match in _URL.finditer(source):
            if clean[match.start() : match.start() + 4].strip():
                record(
                    EntityKind.EXTERNAL_API, match.group(1), {"via": "url"},
                    _line_of(source, match.start()),
                )

        if self.is_entrypoint(relative_path, source):
            record(EntityKind.ENTRYPOINT, relative_path, {"language": self.language})

        return found

    def parse_manifest(self, relative_path: str, source: str) -> list[DetectedEntity]:
        """Dependencies from Maven or Gradle, as `group:artifact`."""
        name = PurePosixPath(relative_path).name
        out: list[DetectedEntity] = []
        seen: set[str] = set()

        def record(group: str, artifact: str) -> None:
            key = f"{group}:{artifact}"
            if key not in seen:
                seen.add(key)
                out.append(DetectedEntity(
                    kind=EntityKind.DEPENDENCY,
                    name=key,
                    data={"ecosystem": "maven", "group": group, "artifact": artifact},
                ))

        if name == "pom.xml":
            for match in _POM_DEPENDENCY.finditer(source):
                record(match.group(1), match.group(2))
        elif name.startswith("build.gradle"):
            for line in source.split("\n"):
                if match := _GRADLE_DEPENDENCY.match(line):
                    record(match.group(1), match.group(2))
        return out


_TYPE_KINDS = {
    "class": SymbolKind.CLASS,
    "interface": SymbolKind.INTERFACE,
    "@interface": SymbolKind.ANNOTATION,
    "enum": SymbolKind.ENUM,
    "record": SymbolKind.STRUCT,
}


def _visibility(keyword: str | None) -> Visibility:
    """
    Package-private is the default, and it is not public.

    Omitting a modifier in Java means "visible within this package" — closer to
    internal than to exported, and treating it as public overstates the API surface
    of every class that leaves it off.
    """
    if keyword == "public":
        return Visibility.PUBLIC
    if keyword == "private":
        return Visibility.PRIVATE
    return Visibility.INTERNAL


def _line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


__all__ = ["JavaProvider"]
