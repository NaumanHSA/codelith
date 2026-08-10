"""
Provider lookup: path/extension → `LanguageProvider`.

The rest of the application asks the registry rather than testing language strings,
so adding a language is a registration, not an edit to a conditional.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from threading import Lock

from codelith.languages.base import LanguageProvider

#: Directories never worth analysing, regardless of language.
DEFAULT_IGNORED_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn",
    ".venv", "venv", "env", "virtualenv",
    "node_modules", "bower_components", "vendor",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "dist", "build", "out", "target", ".next", ".nuxt", ".svelte-kit",
    ".eggs", "coverage", "htmlcov", ".idea", ".vscode",
    ".codegraph", ".terraform",
})


class LanguageRegistry:
    """Thread-safe registry of language providers."""

    def __init__(self) -> None:
        self._providers: dict[str, LanguageProvider] = {}
        self._by_extension: dict[str, LanguageProvider] = {}
        self._lock = Lock()

    def register(self, provider: LanguageProvider, *, replace: bool = False) -> None:
        with self._lock:
            if provider.language in self._providers and not replace:
                raise ValueError(f"language already registered: {provider.language}")
            self._providers[provider.language] = provider
            for ext in provider.extensions:
                self._by_extension[ext.lower()] = provider

    def get(self, language: str) -> LanguageProvider | None:
        return self._providers.get(language)

    def for_path(self, relative_path: str) -> LanguageProvider | None:
        return self._by_extension.get(PurePosixPath(relative_path).suffix.lower())

    def detect(self, relative_path: str) -> str | None:
        provider = self.for_path(relative_path)
        return provider.language if provider else None

    def languages(self) -> list[str]:
        return sorted(self._providers)

    def providers(self) -> list[LanguageProvider]:
        return list(self._providers.values())

    def manifest_providers(self, relative_path: str) -> list[LanguageProvider]:
        """
        Providers that treat this file as a dependency manifest.

        Looked up by filename, not extension: `pyproject.toml` and `go.mod` belong to
        a language even though no provider owns `.toml` or `.mod`.
        """
        name = PurePosixPath(relative_path).name
        return [p for p in self._providers.values() if name in p.manifest_files]

    def extensions(self) -> list[str]:
        return sorted(self._by_extension)

    def ignored_dirs(self) -> frozenset[str]:
        extra: set[str] = set()
        for provider in self._providers.values():
            extra |= set(provider.extra_ignored_dirs)
        return DEFAULT_IGNORED_DIRS | extra

    def should_skip(self, relative_path: str) -> bool:
        # Callers are expected to hand over POSIX-style relative paths, and every one
        # in the tree now does. Backslashes are still split here because the cost of
        # being wrong is asymmetric and silent: `PurePosixPath("node_modules\\x.py")`
        # has a single part, so one native path slipping through means a whole
        # vendored tree is analysed, embedded and billed, with nothing to show that
        # the filter did not fire.
        ignored = self.ignored_dirs()
        parts = PurePosixPath(relative_path.replace("\\", "/")).parts
        return any(part in ignored for part in parts)


#: Process-wide registry. Populated on import of `app.languages`.
registry = LanguageRegistry()


__all__ = ["LanguageRegistry", "registry", "DEFAULT_IGNORED_DIRS"]
