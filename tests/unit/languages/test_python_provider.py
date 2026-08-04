"""Python provider: symbol extraction and language conventions."""

from __future__ import annotations

import textwrap

import pytest

from app.languages.providers.python import PythonProvider
from app.languages.taxonomy import ModuleKind, SymbolKind, Visibility


@pytest.fixture
def provider() -> PythonProvider:
    return PythonProvider()


SAMPLE = textwrap.dedent(
    '''
    """Module docstring."""
    import os

    MAX_RETRIES = 3
    _internal = "x"

    def top_level(a: int, b: str = "y") -> bool:
        """Does a thing."""
        return True

    async def fetch(url: str) -> dict:
        ...

    class Service:
        """A service."""

        timeout = 30

        def __init__(self, db) -> None:
            self.db = db

        async def run(self, payload: dict) -> None:
            ...

        def _helper(self) -> int:
            return 1

        @property
        def name(self) -> str:
            return "svc"
    '''
)


def test_extracts_functions_classes_and_methods(provider: PythonProvider) -> None:
    symbols = {s.qualified_name: s for s in provider.extract_symbols(SAMPLE, "svc.py")}

    assert symbols["top_level"].kind is SymbolKind.FUNCTION
    assert symbols["fetch"].kind is SymbolKind.FUNCTION
    assert symbols["Service"].kind is SymbolKind.CLASS
    assert symbols["Service.__init__"].kind is SymbolKind.CONSTRUCTOR
    assert symbols["Service.run"].kind is SymbolKind.METHOD
    assert symbols["Service.name"].kind is SymbolKind.PROPERTY


def test_constants_and_fields_are_distinguished(provider: PythonProvider) -> None:
    symbols = {s.qualified_name: s for s in provider.extract_symbols(SAMPLE, "svc.py")}

    assert symbols["MAX_RETRIES"].kind is SymbolKind.CONSTANT
    assert symbols["_internal"].kind is SymbolKind.VARIABLE
    # Assignment inside a class body is a field, not a module-level variable.
    assert symbols["Service.timeout"].kind is SymbolKind.FIELD


def test_visibility_follows_python_convention(provider: PythonProvider) -> None:
    symbols = {s.qualified_name: s for s in provider.extract_symbols(SAMPLE, "svc.py")}

    assert symbols["top_level"].visibility is Visibility.PUBLIC
    assert symbols["Service._helper"].visibility is Visibility.INTERNAL
    # Dunders are protocol surface, not private.
    assert symbols["Service.__init__"].visibility is Visibility.PUBLIC
    assert provider.visibility_of("__mangled") is Visibility.PRIVATE


def test_signature_and_docstring_captured(provider: PythonProvider) -> None:
    symbols = {s.qualified_name: s for s in provider.extract_symbols(SAMPLE, "svc.py")}

    assert symbols["top_level"].signature == "def top_level(a: int, b: str='y') -> bool"
    assert symbols["top_level"].docstring == "Does a thing."
    assert symbols["fetch"].signature.startswith("async def fetch")
    assert symbols["Service"].docstring == "A service."


def test_methods_record_their_class(provider: PythonProvider) -> None:
    run = next(s for s in provider.extract_symbols(SAMPLE, "svc.py") if s.name == "run")
    assert run.parent == "Service"
    assert run.qualified_name == "Service.run"


def test_syntax_error_returns_empty_not_raises(provider: PythonProvider) -> None:
    assert provider.extract_symbols("def broken(:\n  pass", "bad.py") == []


def test_symbol_serialisation_is_stable(provider: PythonProvider) -> None:
    sym = next(s for s in provider.extract_symbols(SAMPLE, "svc.py") if s.name == "top_level")
    data = sym.to_dict()

    assert data["name"] == "top_level"
    assert data["kind"] == "function"          # plain string, not an enum repr
    assert data["visibility"] == "public"
    assert isinstance(data["line"], int)


@pytest.mark.parametrize(
    "path,expected_key,expected_kind",
    [
        ("app/agents/base.py", "app/agents", ModuleKind.PACKAGE),
        ("main.py", "main", ModuleKind.FILE),
    ],
)
def test_module_grouping(provider, path, expected_key, expected_kind) -> None:
    ref = provider.module_ref_for(path)
    assert ref.key == expected_key
    assert ref.kind is expected_kind


@pytest.mark.parametrize(
    "path,is_test",
    [
        ("tests/unit/test_x.py", True),
        ("app/foo_test.py", True),
        ("app/services/job_service.py", False),
    ],
)
def test_test_file_detection(provider, path, is_test) -> None:
    assert provider.is_test_file(path) is is_test


def test_entrypoint_detection(provider: PythonProvider) -> None:
    assert provider.is_entrypoint("manage.py", "") is True
    assert provider.is_entrypoint("run.py", 'if __name__ == "__main__":\n    main()') is True
    assert provider.is_entrypoint("app/services/x.py", "x = 1") is False
