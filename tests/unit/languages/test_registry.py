"""Registry behaviour — the seam that keeps language checks out of the codebase."""

from __future__ import annotations

import pytest

from app.languages import registry
from app.languages.base import LanguageProvider, Symbol
from app.languages.registry import LanguageRegistry
from app.languages.taxonomy import SymbolKind


class _FakeGoProvider(LanguageProvider):
    """Stand-in for a future language, used to prove nothing else needs changing."""

    language = "go"
    display_name = "Go"
    extensions = (".go",)
    manifest_files = ("go.mod",)

    def extract_symbols(self, source: str, relative_path: str) -> list[Symbol]:
        return [Symbol(name="main", kind=SymbolKind.FUNCTION, line=1)]


def test_python_is_registered_by_default() -> None:
    assert "python" in registry.languages()
    assert registry.detect("app/main.py") == "python"


def test_unknown_extension_detects_as_none() -> None:
    assert registry.for_path("README.md") is None
    assert registry.detect("image.png") is None


def test_ignored_directories_are_skipped() -> None:
    assert registry.should_skip("ui/node_modules/react/index.py") is True
    assert registry.should_skip("app/__pycache__/x.py") is True
    assert registry.should_skip(".venv/lib/x.py") is True
    assert registry.should_skip("app/agents/base.py") is False


def test_adding_a_language_needs_only_registration() -> None:
    """A new language becomes routable without touching detection logic."""
    local = LanguageRegistry()
    provider = _FakeGoProvider()

    assert local.for_path("cmd/main.go") is None
    local.register(provider)

    assert local.detect("cmd/main.go") == "go"
    assert local.for_path("cmd/main.go") is provider
    assert local.languages() == ["go"]


def test_duplicate_registration_rejected_unless_replacing() -> None:
    local = LanguageRegistry()
    local.register(_FakeGoProvider())

    with pytest.raises(ValueError, match="already registered"):
        local.register(_FakeGoProvider())

    local.register(_FakeGoProvider(), replace=True)  # explicit override is fine


def test_provider_owns_only_its_extensions() -> None:
    provider = _FakeGoProvider()
    assert provider.owns("cmd/main.go") is True
    assert provider.owns("app/main.py") is False


def test_base_defaults_are_usable_without_overrides() -> None:
    """A minimal provider still groups modules and spots tests."""
    provider = _FakeGoProvider()

    ref = provider.module_ref_for("internal/server/http.go")
    assert ref.key == "internal/server"
    assert ref.name == "internal.server"

    assert provider.is_test_file("internal/server/http_test.go") is True
    assert provider.is_entrypoint("cmd/main.go", "") is False
