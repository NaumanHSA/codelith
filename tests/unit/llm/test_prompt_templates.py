"""
The prompt template's one guard.

`SECTION_WRITE` had `"$already_written"` on one line and `"Context:"` on the next.
Adjacent string literals concatenate, so `string.Template` read the identifier as
`already_writtenContext`, found no such key, and left it alone — every writer call
for the life of that prompt was shown the literal text `$already_writtenContext`
instead of the instruction not to repeat the other sections.

The failure is silent by construction: `safe_substitute` is *designed* to leave
unknown placeholders alone. These tests pin the check that turns it loud.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import codelith.llm.prompts as prompts_pkg
from codelith.llm.prompts.base import MissingPromptValue, PromptTemplate


class TestGuard:
    def test_a_supplied_placeholder_renders(self) -> None:
        t = PromptTemplate(system="Hello $name", user="Bye $name")
        assert t.render(name="world")[0]["content"] == "Hello world"

    def test_an_unsupplied_placeholder_raises(self) -> None:
        with pytest.raises(MissingPromptValue, match="missing_one"):
            PromptTemplate(system="$missing_one", user="x").render()

    def test_an_abutting_placeholder_is_caught(self) -> None:
        """The exact shape of the bug: `$a` followed directly by a word."""
        with pytest.raises(MissingPromptValue):
            PromptTemplate(system="x", user="$alreadyContext:").render(already="hi")

    def test_bracing_fixes_it(self) -> None:
        rendered = PromptTemplate(system="x", user="${already}Context:").render(already="hi")
        assert rendered[1]["content"] == "hiContext:"

    def test_a_dollar_in_a_value_is_not_a_placeholder(self) -> None:
        """Source excerpts and shell snippets contain `$`; only the template is checked."""
        rendered = PromptTemplate(system="x", user="$source").render(source="echo $PATH")
        assert rendered[1]["content"] == "echo $PATH"


class TestEveryTemplate:
    """
    Every template in the codebase, rendered with sentinel values.

    A template whose identifiers cannot all be supplied is broken for every caller,
    so this catches the next abutting placeholder at import time rather than in a
    prompt nobody reads.
    """

    @staticmethod
    def _templates() -> list[tuple[str, PromptTemplate]]:
        found = []
        for module in pkgutil.iter_modules(prompts_pkg.__path__):
            mod = importlib.import_module(f"codelith.llm.prompts.{module.name}")
            for name, obj in vars(mod).items():
                if isinstance(obj, PromptTemplate):
                    found.append((f"{module.name}.{name}", obj))
        return found

    def test_the_codebase_has_templates_to_check(self) -> None:
        assert len(self._templates()) >= 10

    def test_every_placeholder_is_a_plausible_identifier(self) -> None:
        """
        `already_writtenContext` is not a name anyone would pass; `module_inventory`
        is. A swallowed placeholder always produces a camelCase tail, because the
        word it swallowed started a new sentence or clause.
        """
        from string import Template

        offenders: list[str] = []
        for name, template in self._templates():
            for part in (template._system, template._user):
                for ident in Template(part).get_identifiers():
                    if ident != ident.lower():
                        offenders.append(f"{name}: ${ident}")

        assert offenders == []
