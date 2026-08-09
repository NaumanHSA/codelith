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


NESTED_ROUTES = textwrap.dedent(
    '''
    def mount_chat_routes(router, server) -> None:
        """Register chat endpoints."""
        local_only = 1

        @router.post("/v1/chat/completions")
        async def chat(body: dict):
            return {}

        @router.get("/v1/models")
        async def models():
            return []
    '''
)


def test_recurses_into_function_bodies(provider: PythonProvider) -> None:
    """
    Regression: a very common FastAPI layout registers routes inside a setup
    function. Stopping at module level made all of them invisible — 28 routes in one
    real project were extracted as 0, so no API Reference was ever suggested.
    """
    names = {s.qualified_name for s in provider.extract_symbols(NESTED_ROUTES, "routes.py")}

    assert "mount_chat_routes" in names
    assert "mount_chat_routes.chat" in names
    assert "mount_chat_routes.models" in names


def test_nested_routes_are_detected_as_entities(provider: PythonProvider) -> None:
    symbols = provider.extract_symbols(NESTED_ROUTES, "routes.py")
    routes = {e.name for e in provider.detect_entities("routes.py", NESTED_ROUTES, symbols)
              if e.kind == "route"}

    assert routes == {"POST /v1/chat/completions", "GET /v1/models"}


def test_function_locals_are_not_treated_as_api_surface(provider: PythonProvider) -> None:
    """Recursing into functions must not flood the KB with local variables."""
    names = {s.name for s in provider.extract_symbols(NESTED_ROUTES, "routes.py")}
    assert "local_only" not in names


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


def _env_names(provider: PythonProvider, source: str, path: str = "app/config.py") -> set[str]:
    symbols = provider.extract_symbols(source, path)
    return {
        e.name
        for e in provider.detect_entities(path, source, symbols)
        if str(e.kind) == "env_var"
    }


class TestEnvironmentVariablesReadThroughAHelper:
    """
    A project that reads more than two variables writes a wrapper, and then
    `os.getenv` never appears at the call sites again.

    Found by scoring answers against the knowledge base: asked what environment
    variables neurosurfer needs, the model named `CONTEXT_WINDOW` and
    `SUPPORTS_VISION`, which the extractor had missed entirely — they are read via
    `env_int(...)` and `env_bool_opt(...)`. The model had read the file. A
    question-answering model should not be better informed about the code than the
    knowledge base it is answering from.
    """

    def test_a_wrapper_call_is_a_read(self, provider: PythonProvider) -> None:
        source = textwrap.dedent(
            """
            from .base import env_int, env_bool_opt

            def load():
                return env_int("CONTEXT_WINDOW", 200_000), env_bool_opt("SUPPORTS_VISION")
            """
        )

        assert {"CONTEXT_WINDOW", "SUPPORTS_VISION"} <= _env_names(provider, source)

    def test_a_qualified_wrapper_counts(self, provider: PythonProvider) -> None:
        source = 'import cfg\n\nX = cfg.env_str("SERVICE_NAME")\n'

        assert "SERVICE_NAME" in _env_names(provider, source)

    def test_an_unrelated_function_is_not_a_read(self, provider: PythonProvider) -> None:
        """The guard has to be narrow, or every constant passed to any function
        becomes configuration the reader is told they must set."""
        source = 'setup("PRODUCTION")\nlog.info("STARTING")\nparse("A_CONSTANT")\n'

        assert _env_names(provider, source) == set()

    def test_a_non_literal_argument_is_not_a_read(self, provider: PythonProvider) -> None:
        source = "def load(key):\n    return env_int(key, 1)\n"

        assert _env_names(provider, source) == set()

    def test_a_lowercase_argument_is_not_a_variable_name(self, provider: PythonProvider) -> None:
        """`env_int(timeout)` reads a field, not `TIMEOUT`."""
        source = 'x = env_int("timeout", 30)\n'

        assert _env_names(provider, source) == set()


class TestEnvironmentVariablesDeclaredByASettingsClass:
    """
    Variables that name themselves nowhere.

    `class ServerSettings(BaseSettings)` with `env_prefix="NS_"` and a field `port`
    declares `NS_PORT`. The string never appears in the source — it is assembled at
    runtime from the prefix and the field name — so no pattern over call sites can
    find it, however clever.

    Found by scoring answers: asked what environment variables neurosurfer needs, the
    model named `NS_HOST`, `NS_PORT` and `NS_LOG_LEVEL`. All three real, none in the
    knowledge base, all three reported to the reader as invented citations.
    document-anything uses the same idiom in `app/config.py`, so until this it could
    not document its own configuration.
    """

    def test_a_prefix_and_a_field_make_a_variable(self, provider: PythonProvider) -> None:
        source = textwrap.dedent(
            """
            from pydantic_settings import BaseSettings, SettingsConfigDict

            class ServerSettings(BaseSettings):
                model_config = SettingsConfigDict(env_prefix="NS_", env_file=".env")

                host: str = "0.0.0.0"
                port: int = 8000
                log_level: str = "info"
            """
        )

        assert _env_names(provider, source) == {"NS_HOST", "NS_PORT", "NS_LOG_LEVEL"}

    def test_the_pydantic_v1_spelling_works_too(self, provider: PythonProvider) -> None:
        """`class Config: env_prefix = ...` is v1. Plenty of code still uses it, and
        it declares exactly the same variables."""
        source = textwrap.dedent(
            """
            from pydantic import BaseSettings

            class Settings(BaseSettings):
                class Config:
                    env_prefix = "APP_"

                database_url: str
            """
        )

        assert _env_names(provider, source) == {"APP_DATABASE_URL"}

    def test_no_prefix_means_the_field_name_is_the_variable(
        self, provider: PythonProvider
    ) -> None:
        source = textwrap.dedent(
            """
            from pydantic_settings import BaseSettings

            class Settings(BaseSettings):
                openai_api_key: str = ""
            """
        )

        assert _env_names(provider, source) == {"OPENAI_API_KEY"}

    def test_an_ordinary_class_declares_nothing(self, provider: PythonProvider) -> None:
        """Annotated fields are how every dataclass in Python is written. Without the
        base-class check this would turn every model in a repository into
        configuration the reader is told they must set."""
        source = textwrap.dedent(
            """
            from dataclasses import dataclass

            @dataclass
            class Point:
                host: str = "x"
                port: int = 1
            """
        )

        assert _env_names(provider, source) == set()

    def test_the_settings_mechanism_is_not_itself_a_setting(
        self, provider: PythonProvider
    ) -> None:
        source = textwrap.dedent(
            """
            from pydantic_settings import BaseSettings, SettingsConfigDict

            class Settings(BaseSettings):
                model_config: SettingsConfigDict = SettingsConfigDict(env_prefix="X_")
                _cache: dict = {}
                real_setting: str = "y"
            """
        )

        assert _env_names(provider, source) == {"X_REAL_SETTING"}
