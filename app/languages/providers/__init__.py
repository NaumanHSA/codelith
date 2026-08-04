"""
Built-in language providers.

To add a language: implement `LanguageProvider` in a module here, then append it to
`BUILTIN_PROVIDERS`. Nothing else in the codebase needs to change.
"""

from __future__ import annotations

from app.languages.base import LanguageProvider
from app.languages.providers.python import PythonProvider

#: Instantiated in registration order. Only Python is implemented today; the seam
#: exists so JavaScript/TypeScript, Go, Java and the rest slot in without touching
#: ingestion, the knowledge base, or the agents.
BUILTIN_PROVIDERS: tuple[LanguageProvider, ...] = (
    PythonProvider(),
)

__all__ = ["BUILTIN_PROVIDERS", "PythonProvider"]
