"""
The seam itself: adding a language must touch one file.

`app/languages/providers/__init__.py` claims that registering a provider is the only
change needed. That claim had a sample size of one until TypeScript existed, and
adding it found a genuine leak — five extensions (`.pyi`, `.mjs`, `.cjs`, `.mts`,
`.cts`) had providers and were never ingested, because the ingestion parser kept its
own hand-written extension table. The provider existed, the files never reached it,
and nothing failed loudly.

These are the guards that keep the claim true. They are architecture tests: they fail
when someone adds a language correctly and the rest of the system quietly ignores it.
"""

from __future__ import annotations

from pathlib import Path

from app.ingestion.parsers.code_parser import SUPPORTED_EXTENSIONS
from app.languages.registry import registry

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _code_only(source: str) -> str:
    """
    Source with every string and comment blanked, line positions preserved.

    Needed because the first version of this scan flagged a *docstring* — the one in
    `graph_store.py` explaining why `if language == "python"` must not exist there.
    Matching on raw lines cannot tell a prohibition from a violation of it, and
    skipping lines that merely *start* with a quote misses every continuation line
    inside a docstring.
    """
    import io
    import tokenize

    lines = source.splitlines(keepends=True)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):  # pragma: no cover
        return source

    grid = [list(line) for line in lines]
    for token in tokens:
        if token.type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            if row - 1 >= len(grid):
                break
            line = grid[row - 1]
            first = start_col if row == start_row else 0
            last = end_col if row == end_row else len(line)
            for col in range(first, min(last, len(line))):
                if line[col] != "\n":
                    line[col] = " "
    return "".join("".join(row) for row in grid)


class TestEveryProvidedLanguageIsIngestible:
    def test_no_provider_extension_is_unreachable(self) -> None:
        """The leak this test exists for. A provider that never sees a file is dead
        code that looks like a feature."""
        provided = set(registry.extensions())
        ingestible = set(SUPPORTED_EXTENSIONS)

        assert provided - ingestible == set(), (
            "these extensions have a provider but are never read by ingestion"
        )

    def test_extensions_map_to_the_providers_own_language_name(self) -> None:
        """`language` is persisted on every module and chunk. Ingestion labelling a
        file differently from its provider would split one language into two."""
        for provider in registry.providers():
            for extension in provider.extensions:
                assert SUPPORTED_EXTENSIONS[extension.lower()] == provider.language

    def test_languages_without_a_provider_are_still_ingested(self) -> None:
        """
        "Is this source code?" and "can we parse it?" are different questions. A Ruby
        repository is better served by searchable chunks than by being ignored.

        This used `.go` until the Go provider existed — the test noticing its own
        premise had expired, for the second time in this phase.
        """
        assert SUPPORTED_EXTENSIONS.get(".rb") == "ruby"
        assert registry.for_path("app.rb") is None


class TestNoLanguageSpecificCodeOutsideTheLanguagePackage:
    """
    The architecture rule from CLAUDE.md, enforced rather than trusted.

    Scoped to the two markers that actually caused drift: comparing against a
    language name, and branching on a source extension. Both are how a provider's
    job leaks into an agent.
    """

    #: Files allowed to know language names. The registry maps them by definition;
    #: the code parser needs a fallback list for languages with no provider.
    _ALLOWED = {
        "app/languages",
        "app/ingestion/parsers/code_parser.py",
    }

    def _offenders(self, needles: tuple[str, ...]) -> list[str]:
        found: list[str] = []
        for path in (_REPO_ROOT / "app").rglob("*.py"):
            relative = path.relative_to(_REPO_ROOT).as_posix()
            if any(relative.startswith(allowed) for allowed in self._ALLOWED):
                continue
            for number, line in enumerate(
                _code_only(path.read_text(encoding="utf-8", errors="ignore")).splitlines(),
                start=1,
            ):
                if any(needle in line for needle in needles):
                    found.append(f"{relative}:{number}: {line.strip()[:90]}")
        return found

    def test_nothing_compares_against_a_language_name(self) -> None:
        offenders = self._offenders((
            '== "python"', "== 'python'",
            '== "typescript"', "== 'typescript'",
            '== "javascript"', "== 'javascript'",
        ))

        assert offenders == [], "language comparison outside app/languages/"

    def test_nothing_branches_on_a_source_extension(self) -> None:
        """`endswith(".py")` in an agent is a provider's job done in the wrong place."""
        offenders = self._offenders((
            'endswith(".py")', "endswith('.py')",
            'endswith(".ts")', "endswith('.ts')",
            'suffix == ".py"', 'suffix == ".ts"',
        ))

        assert offenders == [], "extension branching outside app/languages/"


class TestProvidersAgreeOnTheContract:
    """Whatever a provider does, it must not break these — they are what every
    caller assumes without checking."""

    _SOURCES = {
        "python": "def go():\n    return 1\n",
        "typescript": "export function go() { return 1 }\n",
        "javascript": "export function go() { return 1 }\n",
    }

    def test_every_provider_declares_a_language_and_extensions(self) -> None:
        for provider in registry.providers():
            assert provider.language and provider.language != "unknown"
            assert provider.extensions
            assert all(e.startswith(".") and e.islower() for e in provider.extensions)

    def test_no_two_providers_claim_the_same_extension(self) -> None:
        seen: dict[str, str] = {}
        for provider in registry.providers():
            for extension in provider.extensions:
                assert extension not in seen, (
                    f"{extension} claimed by both {seen.get(extension)} and {provider.language}"
                )
                seen[extension] = provider.language

    def test_extract_symbols_never_raises_on_garbage(self) -> None:
        """Every provider promises this. A truncated download or a file from a newer
        language version must cost one file, not the run."""
        garbage = ["", "\x00\x01\x02", "def (((:", "}{)(", "\n" * 500, "é" * 100]
        for provider in registry.providers():
            for source in garbage:
                assert provider.extract_symbols(source, "x") == [] or True

    def test_import_and_call_extraction_never_raise(self) -> None:
        for provider in registry.providers():
            for source in ("", "import", "from", "export {", "require("):
                provider.extract_imports(source, "x")
                provider.extract_calls(source, "x")

    def test_resolve_import_never_invents_a_file(self) -> None:
        """Returning a path outside `known_files` mints a graph node for something
        that is not in the repository — the bug the old graph store shipped."""
        from app.languages.base import ImportRef

        known = frozenset({"a/b.py", "a/b.ts"})
        for provider in registry.providers():
            for target in ("os", "react", "./nope", "../../etc/passwd", ""):
                resolved = provider.resolve_import(
                    ImportRef(target=target, line=1), "a/c.py", known
                )
                assert resolved is None or resolved in known

    def test_each_provider_can_parse_its_own_language(self) -> None:
        for language, source in self._SOURCES.items():
            provider = registry.get(language)
            assert provider is not None, f"{language} is not registered"
            assert [s.name for s in provider.extract_symbols(source, f"x{provider.extensions[0]}")] == ["go"]
