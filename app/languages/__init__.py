"""
Language support layer.

Everything that differs between programming languages lives behind
`LanguageProvider`. Callers work with the neutral vocabulary in `taxonomy` and look
providers up through the registry:

    from app.languages import registry

    provider = registry.for_path("app/agents/base.py")
    if provider:
        symbols = provider.extract_symbols(source, "app/agents/base.py")

Only Python is implemented today. Adding another language is a new provider module
plus one entry in `providers.BUILTIN_PROVIDERS` — no conditionals elsewhere.
"""

from __future__ import annotations

from app.languages.base import LanguageProvider, ModuleRef, Symbol
from app.languages.providers import BUILTIN_PROVIDERS
from app.languages.registry import DEFAULT_IGNORED_DIRS, LanguageRegistry, registry
from app.languages.taxonomy import ModuleKind, SymbolKind, Visibility

for _provider in BUILTIN_PROVIDERS:
    registry.register(_provider, replace=True)

__all__ = [
    "LanguageProvider",
    "LanguageRegistry",
    "ModuleKind",
    "ModuleRef",
    "Symbol",
    "SymbolKind",
    "Visibility",
    "DEFAULT_IGNORED_DIRS",
    "registry",
]
