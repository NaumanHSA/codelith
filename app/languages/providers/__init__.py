"""
Built-in language providers.

To add a language: implement `LanguageProvider` in a module here, then append it to
`BUILTIN_PROVIDERS`. Nothing else in the codebase needs to change.

That was a claim until TypeScript was added, and it held: registering the second and
third providers touched this tuple and nothing else. No agent, no schema, no
workflow, no branch on a language name anywhere outside this package.
"""

from __future__ import annotations

from app.languages.base import LanguageProvider
from app.languages.providers.python import PythonProvider
from app.languages.providers.typescript import JavaScriptProvider, TypeScriptProvider

#: Instantiated in registration order.
BUILTIN_PROVIDERS: tuple[LanguageProvider, ...] = (
    PythonProvider(),
    TypeScriptProvider(),
    JavaScriptProvider(),
)

__all__ = [
    "BUILTIN_PROVIDERS",
    "PythonProvider",
    "TypeScriptProvider",
    "JavaScriptProvider",
]
