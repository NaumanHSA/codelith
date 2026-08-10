"""
Language-neutral vocabulary for describing code.

Every construct any supported language can express maps onto one of these kinds.
They are deliberately a *superset*: Rust has traits and Python does not, TypeScript
has interfaces and Go has none — a provider maps its native constructs onto the
closest member here and the rest of the system never learns the difference.

These values are persisted (see `kb_modules.symbols_json`), so treat them as a
stable contract: add members freely, never rename or repurpose one.
"""

from __future__ import annotations

from enum import StrEnum


class SymbolKind(StrEnum):
    """A named construct declared in source."""

    # Containers
    MODULE = "module"
    NAMESPACE = "namespace"
    PACKAGE = "package"

    # Types
    CLASS = "class"
    INTERFACE = "interface"
    STRUCT = "struct"
    ENUM = "enum"
    TRAIT = "trait"
    PROTOCOL = "protocol"
    TYPE_ALIAS = "type_alias"

    # Callables
    FUNCTION = "function"
    METHOD = "method"
    CONSTRUCTOR = "constructor"
    PROPERTY = "property"

    # Values
    CONSTANT = "constant"
    VARIABLE = "variable"
    FIELD = "field"

    # Metaprogramming
    MACRO = "macro"
    DECORATOR = "decorator"
    ANNOTATION = "annotation"

    UNKNOWN = "unknown"


class Visibility(StrEnum):
    """
    How widely a symbol is exposed.

    Languages signal this very differently — Python by a leading underscore, Go by
    capitalisation, Java/C# by keyword. Providers normalise to these three so the
    writer can prioritise the public surface without language-specific rules.
    """

    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"


class ModuleKind(StrEnum):
    """
    The unit a group of symbols belongs to.

    "Module" means different things per language — a Python package directory, a Go
    package, a Java package, a single Rust file. Providers decide the grouping; the
    KB only stores the result.
    """

    PACKAGE = "package"
    FILE = "file"
    NAMESPACE = "namespace"
    COMPONENT = "component"
    UNKNOWN = "unknown"


__all__ = ["SymbolKind", "Visibility", "ModuleKind"]
