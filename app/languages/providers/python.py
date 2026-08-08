"""
Python language support.

Uses the stdlib `ast` module rather than line-based heuristics, which is the point of
the provider seam: each language brings the best tool available to it without the
rest of the system caring. A language with no parser available can still ship a
regex-based provider — the interface is identical.
"""

from __future__ import annotations

import ast
import re
import sys
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
from app.languages.providers import _python_entities as python_entities
from app.languages.taxonomy import ModuleKind, SymbolKind, Visibility

#: `@router.get("/x")`, `@app.post("/y")` — FastAPI/Flask-style routing decorators.
_ROUTE_DECORATOR = re.compile(
    r"^(?P<obj>\w+)\.(?P<method>get|post|put|patch|delete|head|options|route)"
    r"\(\s*[\"'](?P<path>[^\"']+)[\"']"
)
#: `os.getenv("X")`, `os.environ["X"]`, `os.environ.get("X")`
_ENV_VAR = re.compile(
    r"""os\.(?:getenv|environ\.get)\(\s*["']([A-Z0-9_]+)["']"""
    r"""|os\.environ\[\s*["']([A-Z0-9_]+)["']"""
)
#: A requirements.txt line: name, optional extras, optional specifier.
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*(\[[^\]]*\])?\s*([<>=!~].*)?$")

_ENTRYPOINT_FILENAMES = frozenset({
    "main.py", "__main__.py", "manage.py", "wsgi.py", "asgi.py", "app.py", "cli.py",
})

#: Directories whose `__main__` blocks are demos, one-off utilities or teaching
#: material rather than ways into the system. A conventional entrypoint *filename*
#: still counts anywhere — this only gates the `__name__ == "__main__"` heuristic.
_NON_ENTRYPOINT_DIRS = frozenset({
    "scripts", "script", "examples", "example", "samples", "tutorials", "tutorial",
    "docs", "benchmarks", "bench", "demo", "demos", "tools", "notebooks",
})

_PROPERTY_DECORATORS = frozenset({"property", "cached_property", "functools.cached_property"})

#: Names that reach `external_package` but are not distributions. `__future__` is
#: a compiler directive, and the rest are stdlib aliases too old to be listed.
_NOT_A_PACKAGE = frozenset({"__future__", "__main__"})


class PythonProvider(LanguageProvider):
    language = "python"
    display_name = "Python"
    extensions = (".py", ".pyi")
    manifest_files = (
        "pyproject.toml", "requirements.txt", "requirements.in",
        "setup.py", "setup.cfg", "Pipfile", "poetry.lock", "uv.lock",
    )

    # ── Symbols ───────────────────────────────────────────────────────────────

    def extract_symbols(self, source: str, relative_path: str) -> list[Symbol]:
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError):
            # Unparseable file (wrong version, generated, truncated) — not fatal.
            return []

        symbols: list[Symbol] = []
        self._walk(tree.body, parent=None, symbols=symbols)
        return symbols

    def _walk(
        self,
        body: list[ast.stmt],
        parent: str | None,
        symbols: list[Symbol],
        in_function: bool = False,
    ) -> None:
        """
        Walk a body, recursing into both classes *and* functions.

        Recursing into functions matters more than it looks: a very common FastAPI
        layout registers every route inside a setup function —

            def mount_chat_routes(router, server):
                @router.post("/v1/chat/completions")
                async def chat(...): ...

        Stopping at module level made all of those invisible. On one real project that
        was 28 routes extracted as 0, which in turn meant no API Reference was ever
        suggested for it.

        Local variables inside a function are skipped: they are noise, not API surface.
        """
        for node in body:
            if isinstance(node, ast.ClassDef):
                symbols.append(
                    Symbol(
                        name=node.name,
                        kind=SymbolKind.CLASS,
                        line=node.lineno,
                        end_line=getattr(node, "end_lineno", None),
                        visibility=self.visibility_of(node.name),
                        docstring=ast.get_docstring(node),
                        parent=parent,
                        decorators=self._decorators(node),
                        signature=self._class_signature(node),
                    )
                )
                # Recurse so methods carry their class as `parent`.
                self._walk(node.body, parent=node.name, symbols=symbols, in_function=False)

            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                decorators = self._decorators(node)
                symbols.append(
                    Symbol(
                        name=node.name,
                        kind=self._callable_kind(node.name, parent, decorators),
                        line=node.lineno,
                        end_line=getattr(node, "end_lineno", None),
                        visibility=self.visibility_of(node.name),
                        signature=self._function_signature(node),
                        docstring=ast.get_docstring(node),
                        parent=parent,
                        decorators=decorators,
                    )
                )
                # Nested defs are where framework registrations live.
                self._walk(node.body, parent=node.name, symbols=symbols, in_function=True)

            elif isinstance(node, ast.Assign | ast.AnnAssign) and not in_function:
                for name in self._assigned_names(node):
                    symbols.append(
                        Symbol(
                            name=name,
                            kind=(
                                SymbolKind.CONSTANT if name.isupper()
                                else SymbolKind.FIELD if parent
                                else SymbolKind.VARIABLE
                            ),
                            line=node.lineno,
                            visibility=self.visibility_of(name),
                            parent=parent,
                        )
                    )

    @staticmethod
    def _assigned_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
        if isinstance(node, ast.AnnAssign):
            return [node.target.id] if isinstance(node.target, ast.Name) else []
        return [t.id for t in node.targets if isinstance(t, ast.Name)]

    @staticmethod
    def _decorators(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        """
        Full decorator expressions, arguments included.

        The arguments matter: `@router.get("/x")` only identifies a route because the
        path is in the call. Unparsing just the callee would throw that away.
        """
        rendered: list[str] = []
        for dec in node.decorator_list:
            try:
                rendered.append(ast.unparse(dec))
            except Exception:  # pragma: no cover - defensive
                continue
        return rendered

    def _callable_kind(self, name: str, parent: str | None, decorators: list[str]) -> SymbolKind:
        if any(d in _PROPERTY_DECORATORS for d in decorators):
            return SymbolKind.PROPERTY
        if parent is None:
            return SymbolKind.FUNCTION
        return SymbolKind.CONSTRUCTOR if name == "__init__" else SymbolKind.METHOD

    @staticmethod
    def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        try:
            args = ast.unparse(node.args)
        except Exception:  # pragma: no cover - defensive
            args = "..."
        returns = ""
        if node.returns is not None:
            try:
                returns = f" -> {ast.unparse(node.returns)}"
            except Exception:  # pragma: no cover - defensive
                returns = ""
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return f"{prefix} {node.name}({args}){returns}"

    @staticmethod
    def _class_signature(node: ast.ClassDef) -> str:
        bases: list[str] = []
        for base in node.bases:
            try:
                bases.append(ast.unparse(base))
            except Exception:  # pragma: no cover - defensive
                continue
        return f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"

    # ── Conventions ───────────────────────────────────────────────────────────

    def visibility_of(self, name: str) -> Visibility:
        if name.startswith("__") and name.endswith("__"):
            return Visibility.PUBLIC          # dunder: part of the protocol surface
        if name.startswith("__"):
            return Visibility.PRIVATE         # name-mangled
        if name.startswith("_"):
            return Visibility.INTERNAL
        return Visibility.PUBLIC

    def module_ref_for(self, relative_path: str) -> ModuleRef:
        p = PurePosixPath(relative_path)
        parent = p.parent.as_posix()
        if parent in ("", "."):
            return ModuleRef(key=p.stem, name=p.stem, kind=ModuleKind.FILE)
        return ModuleRef(key=parent, name=parent.replace("/", "."), kind=ModuleKind.PACKAGE)

    def is_test_file(self, relative_path: str) -> bool:
        p = PurePosixPath(relative_path)
        if p.name.startswith("test_") or p.stem.endswith("_test"):
            return True
        return any(part in ("tests", "test", "testing") for part in p.parts)

    def is_entrypoint(self, relative_path: str, source: str) -> bool:
        """
        Whether this file is a way *into the system*.

        A bare `if __name__ == "__main__"` is not enough on its own. Run 1 recorded 10
        entrypoints for neurosurfer, of which five were noise — `tests/test_mcp_client.py`,
        two one-off SVG scripts and two tutorial files — and every one of them was then
        echoed into the architecture map and the diagram prompt as a fact about the
        system. Tests, examples and scratch scripts are excluded; a conventional
        entrypoint filename still qualifies wherever it lives.
        """
        path = PurePosixPath(relative_path)
        if self.is_test_file(relative_path):
            return False
        if path.name in _ENTRYPOINT_FILENAMES:
            return True
        if any(part in _NON_ENTRYPOINT_DIRS for part in path.parts):
            return False
        return python_entities.has_main_guard(source)

    # ── Graph ─────────────────────────────────────────────────────────────────

    def extract_imports(self, source: str, relative_path: str) -> list[ImportRef]:
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError):
            return []

        refs: list[ImportRef] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    refs.append(ImportRef(target=alias.name, line=node.lineno))
            elif isinstance(node, ast.ImportFrom):
                # `from . import x` has no module; the package itself is the target.
                refs.append(
                    ImportRef(
                        target=node.module or "",
                        line=node.lineno,
                        names=tuple(a.name for a in node.names),
                        level=node.level or 0,
                    )
                )
        return refs

    def resolve_import(
        self, ref: ImportRef, from_path: str, known_files: frozenset[str]
    ) -> str | None:
        """
        A dotted module path to a file in this repository.

        Both spellings of a package are tried — `a/b.py` and `a/b/__init__.py` — and
        the result is only returned if it is a file we actually saw. Anything else is
        third-party, stdlib, or a namespace package we cannot place, and inventing a
        node for it would fill the graph with things that do not exist.
        """
        parts = [p for p in ref.target.split(".") if p]

        if ref.level:
            # Relative: walk up from the importing file's package. Level 1 is the
            # containing directory, so the first step up is already accounted for.
            base = PurePosixPath(from_path).parent
            for _ in range(ref.level - 1):
                base = base.parent
            prefix = [p for p in base.as_posix().split("/") if p and p != "."]
            parts = prefix + parts

        if not parts:
            return None

        for candidate in (
            "/".join(parts) + ".py",
            "/".join(parts) + "/__init__.py",
        ):
            if candidate in known_files:
                return candidate

        # `from app.db.session import X` where `session` is a symbol in `app/db.py`
        # rather than a module — drop the last segment and try the parent.
        if len(parts) > 1:
            for candidate in (
                "/".join(parts[:-1]) + ".py",
                "/".join(parts[:-1]) + "/__init__.py",
            ):
                if candidate in known_files:
                    return candidate
        return None

    def external_package(self, ref: ImportRef) -> str | None:
        """
        The distribution a non-repository import comes from.

        Stdlib is dropped: `sys.stdlib_module_names` is exact, and without it the
        package edges are mostly `typing`, `__future__` and `pathlib` — 4,862 edges
        on this repository, of which the large majority said nothing about what the
        software depends on.

        The top-level name only, so `openai.types.chat` records `openai` once rather
        than burying it under submodules.
        """
        if ref.level:
            return None  # relative, and unresolved means the file simply is not there
        root = ref.target.split(".")[0].strip()
        if not root or root in sys.stdlib_module_names or root in _NOT_A_PACKAGE:
            return None
        return root

    def extract_calls(self, source: str, relative_path: str) -> list[CallRef]:
        """
        Call sites, attributed to the function or method containing them.

        Only the callee's *name* is recorded — `self.db.commit()` yields `commit`.
        Resolving that to a definition is the graph builder's job and is allowed to
        fail; a name that matches nothing is dropped rather than guessed at.
        """
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError):
            return []

        calls: list[CallRef] = []

        def walk(node: ast.AST, caller: str | None, parent: str | None) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    walk(child, caller, child.name)
                    continue
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = f"{parent}.{child.name}" if parent else child.name
                    walk(child, name, parent)
                    continue
                if isinstance(child, ast.Call) and caller:
                    if name := self._callee_name(child.func):
                        calls.append(CallRef(caller=caller, callee=name, line=child.lineno))
                walk(child, caller, parent)

        walk(tree, None, None)
        return calls

    @staticmethod
    def _callee_name(func: ast.expr) -> str | None:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    # ── Entity detection ──────────────────────────────────────────────────────

    def detect_entities(
        self, relative_path: str, source: str, symbols: list[Symbol]
    ) -> list[DetectedEntity]:
        found: list[DetectedEntity] = []

        # HTTP routes, read off the decorators the AST already captured.
        for symbol in symbols:
            for decorator in symbol.decorators:
                match = _ROUTE_DECORATOR.match(decorator)
                if not match:
                    continue
                method = match.group("method").upper()
                path = match.group("path")
                found.append(
                    DetectedEntity(
                        kind=EntityKind.ROUTE,
                        name=f"{method} {path}" if method != "ROUTE" else path,
                        data={
                            "method": None if method == "ROUTE" else method,
                            "path": path,
                            "handler": symbol.qualified_name,
                            "router": match.group("obj"),
                        },
                        line=symbol.line,
                    )
                )

        # Environment variables the code reads. Read off the AST rather than the raw
        # text: a regex also matches the comment *documenting* the pattern, and this
        # file's own `#: os.getenv("X")` was being extracted as an env var called X.
        found.extend(python_entities.env_vars(source))

        if self.is_entrypoint(relative_path, source):
            found.append(
                DetectedEntity(
                    kind=EntityKind.ENTRYPOINT,
                    name=relative_path,
                    data={"language": self.language},
                )
            )

        # Datastores, external APIs, CLI commands, scheduled work, events and
        # services. `imported_roots` lets a detector require that the file actually
        # imported the library it is about — `connect()` means nothing without it.
        found.extend(
            python_entities.detect(
                relative_path,
                source,
                symbols,
                imported_roots={
                    ref.target.split(".")[0]
                    for ref in self.extract_imports(source, relative_path)
                    if ref.target
                },
            )
        )

        return found

    def parse_manifest(self, relative_path: str, source: str) -> list[DetectedEntity]:
        name = PurePosixPath(relative_path).name
        if name in ("requirements.txt", "requirements.in"):
            return self._parse_requirements(source)
        if name == "pyproject.toml":
            return self._parse_pyproject(source)
        return []

    def _parse_requirements(self, source: str) -> list[DetectedEntity]:
        out: list[DetectedEntity] = []
        for raw in source.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            match = _REQUIREMENT.match(line)
            if match:
                out.append(
                    DetectedEntity(
                        kind=EntityKind.DEPENDENCY,
                        name=match.group(1),
                        data={"ecosystem": "pypi", "specifier": (match.group(3) or "").strip()},
                    )
                )
        return out

    def _parse_pyproject(self, source: str) -> list[DetectedEntity]:
        try:
            import tomllib

            data = tomllib.loads(source)
        except Exception:
            return []

        raw_deps: list[str] = []
        project = data.get("project", {})
        if isinstance(project.get("dependencies"), list):
            raw_deps += [d for d in project["dependencies"] if isinstance(d, str)]
        for extra in (project.get("optional-dependencies") or {}).values():
            if isinstance(extra, list):
                raw_deps += [d for d in extra if isinstance(d, str)]

        out: list[DetectedEntity] = []
        seen: set[str] = set()
        for spec in raw_deps:
            match = _REQUIREMENT.match(spec.split(";", 1)[0].strip())
            if not match or match.group(1) in seen:
                continue
            seen.add(match.group(1))
            out.append(
                DetectedEntity(
                    kind=EntityKind.DEPENDENCY,
                    name=match.group(1),
                    data={"ecosystem": "pypi", "specifier": (match.group(3) or "").strip()},
                )
            )
        return out


__all__ = ["PythonProvider"]
