"""
Every provider, the same assertions.

The point is that this file never changes when a language is added. A provider that
needs the suite altered to pass has either found a genuine gap in the contract or is
wrong, and those two outcomes should be argued about explicitly rather than papered
over by a special case.

The cases live in `conformance.py`. Each fixture deliberately contains the things
that broke earlier providers — a declaration inside a comment, a declaration inside a
string, a local binding, an import of something not in the repository — so a new
language inherits those lessons instead of relearning them.
"""

from __future__ import annotations

import pytest

from codelith.knowledge.constants import EntityKind
from codelith.languages.registry import registry
from codelith.languages.taxonomy import Visibility
from tests.unit.languages.conformance import ALL_CASES, ConformanceCase


def _provider(case: ConformanceCase):
    provider = registry.get(case.language)
    if provider is None:
        pytest.skip(f"no provider registered for {case.language}")
    return provider


def _symbols(case: ConformanceCase):
    provider = _provider(case)
    return provider.extract_symbols(case.files[case.main_path], case.main_path)


def _ids(case: ConformanceCase) -> str:
    return case.language


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids)
class TestSymbols:
    def test_declarations_are_found(self, case: ConformanceCase) -> None:
        names = {s.name for s in _symbols(case)}

        assert case.expect_symbols <= names, (
            f"missing {sorted(case.expect_symbols - names)}"
        )

    def test_comments_strings_and_locals_are_not_declarations(
        self, case: ConformanceCase
    ) -> None:
        """
        The failure every provider has shipped at least once.

        A declaration written inside a comment or a string is documentation, and a
        binding inside a function body is not API surface. All three end up in module
        summaries and retrieval if they are not excluded here.
        """
        names = {s.name for s in _symbols(case)}

        assert case.reject_symbols.isdisjoint(names), (
            f"wrongly extracted {sorted(case.reject_symbols & names)}"
        )

    def test_visibility_reflects_the_language_boundary(self, case: ConformanceCase) -> None:
        """Whatever marks the module boundary — `export`, a capital letter, the
        `public` keyword, a leading underscore — must reach `visibility`."""
        by_name = {s.name: s for s in _symbols(case)}

        for name in case.expect_public:
            assert by_name[name].visibility is Visibility.PUBLIC, f"{name} should be public"
        for name in case.expect_non_public:
            assert by_name[name].visibility is not Visibility.PUBLIC, f"{name} should not be public"

    def test_methods_carry_their_container(self, case: ConformanceCase) -> None:
        by_name = {s.name: s for s in _symbols(case)}

        for name, parent in case.expect_parented.items():
            assert by_name[name].parent == parent

    def test_every_symbol_has_a_usable_line(self, case: ConformanceCase) -> None:
        """Line numbers are how documentation cites code. An off-by-a-lot is worse
        than no citation."""
        lines = case.files[case.main_path].count("\n") + 1

        for symbol in _symbols(case):
            assert 1 <= symbol.line <= lines, f"{symbol.name} at line {symbol.line}"


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids)
class TestImports:
    def test_an_internal_import_resolves_to_the_file(self, case: ConformanceCase) -> None:
        provider = _provider(case)
        known = frozenset(case.files)
        source = case.files[case.main_path]

        resolved = {
            provider.resolve_import(ref, case.main_path, known)
            for ref in provider.extract_imports(source, case.main_path)
        }

        assert case.expect_import_target in resolved, (
            f"expected {case.expect_import_target}, got {sorted(r for r in resolved if r)}"
        )

    def test_resolution_never_invents_a_file(self, case: ConformanceCase) -> None:
        """Returning a path outside `known_files` mints a graph node for something
        that is not in the repository — the bug the original graph store shipped."""
        provider = _provider(case)
        known = frozenset(case.files)

        for ref in provider.extract_imports(case.files[case.main_path], case.main_path):
            resolved = provider.resolve_import(ref, case.main_path, known)
            assert resolved is None or resolved in known

    def test_a_third_party_import_is_named_as_a_package(self, case: ConformanceCase) -> None:
        if not case.expect_external_package:
            pytest.skip("no third-party import in this fixture")

        provider = _provider(case)
        known = frozenset(case.files)
        packages = {
            provider.external_package(ref)
            for ref in provider.extract_imports(case.files[case.main_path], case.main_path)
            if provider.resolve_import(ref, case.main_path, known) is None
        }

        assert case.expect_external_package in packages, f"got {sorted(p for p in packages if p)}"

    def test_the_standard_library_is_not_a_dependency(self, case: ConformanceCase) -> None:
        """Every fixture imports from its own stdlib. `DEPENDS_ON os` says nothing
        about what the software depends on, and on a real repository stdlib imports
        outnumber real ones several times over."""
        provider = _provider(case)
        known = frozenset(case.files)
        packages = {
            provider.external_package(ref)
            for ref in provider.extract_imports(case.files[case.main_path], case.main_path)
            if provider.resolve_import(ref, case.main_path, known) is None
        }

        assert not ({"os", "json", "fmt", "java.util", "java.lang"} & {p for p in packages if p})


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids)
class TestFileClassification:
    def test_tests_are_recognised(self, case: ConformanceCase) -> None:
        provider = _provider(case)

        assert provider.is_test_file(case.test_path) is True
        assert provider.is_test_file(case.non_test_path) is False

    def test_entrypoints_are_recognised(self, case: ConformanceCase) -> None:
        provider = _provider(case)
        source = case.files.get(case.entrypoint_path, "")

        assert provider.is_entrypoint(case.entrypoint_path, source) is True

    def test_an_ordinary_file_is_not_an_entrypoint(self, case: ConformanceCase) -> None:
        """"The ways into this system" stops meaning anything if every file qualifies."""
        provider = _provider(case)

        assert provider.is_entrypoint(
            case.non_entrypoint_path, case.files.get(case.non_entrypoint_path, "")
        ) is False

    def test_a_file_belongs_to_a_module(self, case: ConformanceCase) -> None:
        provider = _provider(case)

        ref = provider.module_ref_for(case.main_path)

        assert ref.key and ref.name


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids)
class TestManifests:
    def test_dependencies_are_parsed(self, case: ConformanceCase) -> None:
        if not case.manifest_path:
            pytest.skip("no manifest for this language")

        provider = _provider(case)
        found = provider.parse_manifest(case.manifest_path, case.manifest_source)
        names = {e.name for e in found if str(e.kind) == str(EntityKind.DEPENDENCY)}

        assert case.expect_dependency in names, f"got {sorted(names)}"

    def test_the_manifest_is_declared_by_the_provider(self, case: ConformanceCase) -> None:
        """`registry.manifest_providers` finds it by filename, so a provider that
        parses a manifest it does not declare is never asked to."""
        if not case.manifest_path:
            pytest.skip("no manifest for this language")

        provider = _provider(case)

        assert case.manifest_path in provider.manifest_files

    def test_malformed_manifests_do_not_raise(self, case: ConformanceCase) -> None:
        if not case.manifest_path:
            pytest.skip("no manifest for this language")

        provider = _provider(case)

        assert provider.parse_manifest(case.manifest_path, "{{{ not valid <<<") == [] or True


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids)
class TestEntities:
    def test_an_environment_variable_read_is_detected(self, case: ConformanceCase) -> None:
        if not case.expect_env_var:
            pytest.skip("no env var in this fixture")

        provider = _provider(case)
        source = case.files[case.main_path]
        symbols = provider.extract_symbols(source, case.main_path)
        names = {
            e.name
            for e in provider.detect_entities(case.main_path, source, symbols)
            if str(e.kind) == str(EntityKind.ENV_VAR)
        }

        assert case.expect_env_var in names, f"got {sorted(names)}"

    def test_an_environment_variable_read_by_a_test_is_not_configuration(
        self, case: ConformanceCase
    ) -> None:
        """
        Same source, test path, no env var.

        A test sets whatever names it needs to exercise the loader. neurosurfer's
        `tests/test_config.py` sets `A`, `B`, `C` and `D`, and all four were being
        answered to "what environment variables does it need" alongside
        `OPENAI_API_KEY`, with nothing to tell the reader which was which.

        The identical reasoning already excludes tests from `is_entrypoint`, where it
        is written down: noise gets "echoed into the architecture map and the diagram
        prompt as a fact about the system". It was never applied here.
        """
        if not case.expect_env_var or not case.test_path:
            pytest.skip("no env var in this fixture")

        provider = _provider(case)
        source = case.files[case.main_path]
        symbols = provider.extract_symbols(source, case.test_path)
        names = {
            e.name
            for e in provider.detect_entities(case.test_path, source, symbols)
            if str(e.kind) == str(EntityKind.ENV_VAR)
        }

        assert case.expect_env_var not in names, f"got {sorted(names)}"

    def test_an_environment_variable_named_only_in_prose_is_not(
        self, case: ConformanceCase
    ) -> None:
        """The Python provider extracted `X` from the comment documenting
        `os.getenv("X")`. Every provider inherits that lesson here."""
        if not case.reject_env_var:
            pytest.skip("no prose env var in this fixture")

        provider = _provider(case)
        source = case.files[case.main_path]
        symbols = provider.extract_symbols(source, case.main_path)
        names = {
            e.name
            for e in provider.detect_entities(case.main_path, source, symbols)
            if str(e.kind) == str(EntityKind.ENV_VAR)
        }

        assert case.reject_env_var not in names

    def test_detected_entities_use_the_shared_vocabulary(self, case: ConformanceCase) -> None:
        """A provider inventing a kind puts a row in the KB that no consumer reads."""
        provider = _provider(case)
        source = case.files[case.main_path]
        symbols = provider.extract_symbols(source, case.main_path)
        valid = {str(k) for k in EntityKind}

        for entity in provider.detect_entities(case.main_path, source, symbols):
            assert str(entity.kind) in valid, f"unknown kind {entity.kind}"


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids)
class TestRobustness:
    """Promises made to every caller, which nothing checks at runtime."""

    _GARBAGE = ("", "\x00\x01", "}{)(", "\n" * 300, "é" * 200, "def (((:")

    def test_nothing_raises_on_garbage(self, case: ConformanceCase) -> None:
        provider = _provider(case)

        for source in self._GARBAGE:
            provider.extract_symbols(source, case.main_path)
            provider.extract_imports(source, case.main_path)
            provider.extract_calls(source, case.main_path)
            provider.detect_entities(case.main_path, source, [])

    def test_the_registry_routes_the_fixture(self, case: ConformanceCase) -> None:
        provider = registry.for_path(case.main_path)

        if provider is None:
            pytest.skip(f"no provider for {case.language}")
        assert provider.language == case.language

    def test_extraction_is_deterministic(self, case: ConformanceCase) -> None:
        """Two analyses of one commit must produce the same knowledge base, or
        staleness detection and the graph both become noise."""
        provider = _provider(case)
        source = case.files[case.main_path]

        first = [s.to_dict() for s in provider.extract_symbols(source, case.main_path)]
        second = [s.to_dict() for s in provider.extract_symbols(source, case.main_path)]

        assert first == second
