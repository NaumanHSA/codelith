"""
The TypeScript provider — and the seam it exists to test.

`LanguageProvider` claimed that adding a language touches one file. That was a claim
with a sample size of one until this provider existed.

The interesting risk is different from Python's. There is no stdlib TypeScript
parser, so this provider is a line scanner, which means **it can read its own
documentation as code**. The Python provider shipped that bug three separate times —
`is_entrypoint` matched the comment explaining the `__main__` idiom, and
`os.getenv("X")` in a docstring became an environment variable named `X`. A regex
provider has no AST to fall back on, so most of these cases are about comments,
strings and JSX being excluded.
"""

from __future__ import annotations

from codelith.knowledge.constants import EntityKind
from codelith.languages.providers.typescript import (
    JavaScriptProvider,
    TypeScriptProvider,
    _strip_noise,
)
from codelith.languages.registry import registry
from codelith.languages.taxonomy import SymbolKind, Visibility

ts = TypeScriptProvider()

COMPONENT = """\
import { useState, useEffect } from 'react'
import { api, ApiError } from '../../lib/api'

export interface ReviseTarget {
  anchor: string
  title: string
}

const MAX_TURNS = 6

export function RevisePanel({ target }: { target: ReviseTarget }) {
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  async function send(text: string) {
    return api.post('/revise', { text })
  }

  return <div className="panel">{busy ? 'working' : 'idle'}</div>
}

export default RevisePanel
"""


class TestSymbols:
    def test_exported_declarations_are_found(self) -> None:
        symbols = {s.name: s for s in ts.extract_symbols(COMPONENT, "ui/src/Panel.tsx")}

        assert symbols["ReviseTarget"].kind is SymbolKind.INTERFACE
        assert symbols["RevisePanel"].kind is SymbolKind.FUNCTION
        assert symbols["MAX_TURNS"].kind is SymbolKind.CONSTANT

    def test_function_locals_are_not_symbols(self) -> None:
        """`const box = useRef(...)` is not API surface. Measured on the studio:
        456 of 740 symbols were function-local bindings before this rule, crowding
        the real declarations out of every summary."""
        names = {s.name for s in ts.extract_symbols(COMPONENT, "ui/src/Panel.tsx")}

        assert "box" not in names
        assert "busy" not in names

    def test_a_nested_handler_is_still_a_symbol(self) -> None:
        """A React handler is real structure, unlike a local binding."""
        names = {s.name for s in ts.extract_symbols(COMPONENT, "ui/src/Panel.tsx")}

        assert "send" in names

    def test_an_arrow_const_is_a_function_not_a_variable(self) -> None:
        source = "export const useJob = (id: number) => { return id }\n"

        symbol = ts.extract_symbols(source, "x.ts")[0]

        assert symbol.kind is SymbolKind.FUNCTION

    def test_export_is_the_visibility_boundary(self) -> None:
        """An unexported declaration cannot be referenced from another file, whatever
        it is named — that is the module boundary in this language."""
        source = "export const shown = 1\nconst hidden = 2\n"

        symbols = {s.name: s for s in ts.extract_symbols(source, "x.ts")}

        assert symbols["shown"].visibility is Visibility.PUBLIC
        assert symbols["hidden"].visibility is Visibility.INTERNAL

    def test_class_methods_carry_their_class(self) -> None:
        source = (
            "export class ApiClient {\n"
            "  private token: string\n"
            "  constructor(t: string) { this.token = t }\n"
            "  async get(path: string) { return fetch(path) }\n"
            "}\n"
        )

        symbols = {s.name: s for s in ts.extract_symbols(source, "x.ts")}

        assert symbols["ApiClient"].kind is SymbolKind.CLASS
        assert symbols["get"].parent == "ApiClient"
        assert symbols["constructor"].kind is SymbolKind.CONSTRUCTOR

    def test_control_flow_is_not_a_method(self) -> None:
        """`if (x) {` and `method(x) {` are the same shape to a line scanner. Without
        the keyword guard, every branch in a class became a method."""
        source = (
            "export class Thing {\n"
            "  run() {\n"
            "    if (this.ok) { return 1 }\n"
            "    for (const a of b) { console.log(a) }\n"
            "    while (x) { break }\n"
            "  }\n"
            "}\n"
        )

        names = {s.name for s in ts.extract_symbols(source, "x.ts")}

        assert names == {"Thing", "run"}


class TestCommentsAndStringsAreNotCode:
    """The failure mode a regex provider is uniquely exposed to."""

    def test_a_declaration_in_a_line_comment_is_ignored(self) -> None:
        source = "// export function ghost() {}\nexport const real = 1\n"

        names = {s.name for s in ts.extract_symbols(source, "x.ts")}

        assert names == {"real"}

    def test_a_declaration_in_a_block_comment_is_ignored(self) -> None:
        source = "/*\n export class Ghost {}\n export function alsoGhost() {}\n*/\nexport const real = 1\n"

        names = {s.name for s in ts.extract_symbols(source, "x.ts")}

        assert names == {"real"}

    def test_a_declaration_inside_a_template_literal_is_ignored(self) -> None:
        source = "export const tpl = `\nexport function ghost() {}\n`\n"

        names = {s.name for s in ts.extract_symbols(source, "x.ts")}

        assert names == {"tpl"}

    def test_stripping_preserves_line_numbers(self) -> None:
        """Reported lines must still describe the original file, or every citation
        in the documentation points at the wrong place."""
        source = "// a comment\n/* another\n spanning lines */\nexport const real = 1\n"

        symbol = ts.extract_symbols(source, "x.ts")[0]

        assert symbol.line == 4

    def test_an_env_var_in_a_comment_is_not_extracted(self) -> None:
        """The exact bug the Python provider shipped, in a language with no AST to
        fall back on."""
        source = "// reads import.meta.env.VITE_GHOST at build time\nconst x = 1\n"

        found = ts.detect_entities("x.ts", source, [])

        assert [e.name for e in found if str(e.kind) == str(EntityKind.ENV_VAR)] == []

    def test_a_real_env_var_read_is_extracted(self) -> None:
        source = "const base = import.meta.env.VITE_API_URL\nconst k = process.env.NODE_ENV\n"

        names = {e.name for e in ts.detect_entities("x.ts", source, [])}

        assert {"VITE_API_URL", "NODE_ENV"} <= names


class TestImports:
    def test_named_and_default_imports_are_captured(self) -> None:
        refs = {r.target: r for r in ts.extract_imports(COMPONENT, "ui/src/Panel.tsx")}

        assert set(refs) == {"react", "../../lib/api"}
        assert "useState" in refs["react"].names
        assert "ApiError" in refs["../../lib/api"].names

    def test_an_aliased_import_records_the_local_name(self) -> None:
        """`{ get as fetchIt }` — call sites use `fetchIt`, so that is the name that
        can resolve a call."""
        source = "import { get as fetchIt } from './api'\n"

        ref = ts.extract_imports(source, "a/b.ts")[0]

        assert "fetchIt" in ref.names

    def test_a_require_call_is_an_import(self) -> None:
        source = "const lib = require('./helpers')\n"

        assert ts.extract_imports(source, "a/b.js")[0].target == "./helpers"

    def test_a_re_export_is_an_import(self) -> None:
        source = "export { thing } from './thing'\n"

        assert ts.extract_imports(source, "a/b.ts")[0].target == "./thing"


class TestImportResolution:
    KNOWN = frozenset({
        "ui/src/lib/api.ts",
        "ui/src/components/Panel.tsx",
        "ui/src/lib/index.ts",
    })

    def _resolve(self, target: str, from_path: str) -> str | None:
        from codelith.languages.base import ImportRef

        return ts.resolve_import(ImportRef(target=target, line=1), from_path, self.KNOWN)

    def test_a_relative_import_gains_the_right_extension(self) -> None:
        assert self._resolve("./api", "ui/src/lib/hooks.ts") == "ui/src/lib/api.ts"

    def test_a_parent_relative_import_resolves(self) -> None:
        assert self._resolve("../lib/api", "ui/src/components/Panel.tsx") == "ui/src/lib/api.ts"

    def test_a_directory_import_finds_the_index(self) -> None:
        assert self._resolve("../lib", "ui/src/components/Panel.tsx") == "ui/src/lib/index.ts"

    def test_a_bare_specifier_is_never_a_repository_file(self) -> None:
        """`react` is a package. Returning a path for it would mint a File node for
        something that is not in the repository."""
        assert self._resolve("react", "ui/src/Panel.tsx") is None

    def test_an_unresolvable_relative_import_returns_none(self) -> None:
        assert self._resolve("./missing", "ui/src/lib/hooks.ts") is None


class TestExternalPackages:
    def _pkg(self, target: str) -> str | None:
        from codelith.languages.base import ImportRef

        return ts.external_package(ImportRef(target=target, line=1))

    def test_a_plain_package(self) -> None:
        assert self._pkg("react") == "react"

    def test_a_subpath_records_the_package(self) -> None:
        assert self._pkg("react-dom/client") == "react-dom"

    def test_a_scoped_package_keeps_both_segments(self) -> None:
        """`@tanstack` alone would merge every unrelated library from that
        organisation into one node."""
        assert self._pkg("@tanstack/react-query") == "@tanstack/react-query"

    def test_a_relative_import_is_not_a_package(self) -> None:
        assert self._pkg("./local") is None


class TestEntrypoints:
    def test_a_root_main_is_an_entrypoint(self) -> None:
        assert ts.is_entrypoint("ui/src/main.tsx", "") is True

    def test_a_deep_index_barrel_is_not(self) -> None:
        """`index.ts` is a re-export barrel in nearly every directory of a real
        project. Counting all of them makes "the ways in" meaningless."""
        assert ts.is_entrypoint("ui/src/app/components/docs/index.ts", "") is False

    def test_a_test_file_is_never_an_entrypoint(self) -> None:
        assert ts.is_entrypoint("src/main.test.ts", "") is False


class TestTestDetection:
    def test_spec_and_test_suffixes(self) -> None:
        assert ts.is_test_file("src/api.test.ts") is True
        assert ts.is_test_file("src/api.spec.tsx") is True

    def test_test_directories(self) -> None:
        assert ts.is_test_file("src/__tests__/api.ts") is True
        assert ts.is_test_file("e2e/flow.ts") is True

    def test_ordinary_source_is_not_a_test(self) -> None:
        assert ts.is_test_file("src/lib/api.ts") is False


class TestManifest:
    MANIFEST = """
    {
      "name": "studio",
      "dependencies": { "react": "^19.0.0", "@tanstack/react-query": "^5.0.0" },
      "devDependencies": { "vite": "^8.0.0" },
      "scripts": { "dev": "vite", "build": "tsc && vite build" }
    }
    """

    def test_dependencies_are_extracted(self) -> None:
        found = ts.parse_manifest("package.json", self.MANIFEST)
        deps = {e.name: e for e in found if str(e.kind) == str(EntityKind.DEPENDENCY)}

        assert set(deps) == {"react", "@tanstack/react-query", "vite"}
        assert deps["vite"].data["dev"] is True
        assert deps["react"].data["dev"] is False

    def test_scripts_become_cli_commands(self) -> None:
        found = ts.parse_manifest("package.json", self.MANIFEST)
        commands = {e.name for e in found if str(e.kind) == str(EntityKind.CLI_COMMAND)}

        assert commands == {"npm run dev", "npm run build"}

    def test_malformed_json_does_not_raise(self) -> None:
        assert ts.parse_manifest("package.json", "{not json") == []


class TestRegistration:
    def test_the_registry_routes_typescript_files(self) -> None:
        for path in ("ui/src/main.tsx", "ui/src/lib/api.ts"):
            provider = registry.for_path(path)
            assert provider is not None
            assert provider.language == "typescript"

    def test_javascript_is_its_own_language(self) -> None:
        """`language` is persisted on every module and chunk. A JavaScript project
        should be able to report that it is JavaScript."""
        provider = registry.for_path("scripts/build.js")

        assert isinstance(provider, JavaScriptProvider)
        assert provider.language == "javascript"

    def test_javascript_shares_the_typescript_grammar(self) -> None:
        source = "export function go() { return 1 }\n"

        assert JavaScriptProvider().extract_symbols(source, "a.js")[0].name == "go"


class TestStripNoise:
    def test_positions_are_preserved_exactly(self) -> None:
        source = "const a = 'hello'\n// gone\n"

        stripped = _strip_noise(source)

        assert len(stripped) == len(source)
        assert stripped.count("\n") == source.count("\n")

    def test_an_escaped_quote_does_not_end_the_string(self) -> None:
        source = "const a = 'it\\'s fine'\nexport const real = 1\n"

        names = {s.name for s in ts.extract_symbols(source, "x.ts")}

        assert "real" in names
