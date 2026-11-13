"""
Every rule's short name: how findings are grouped on the page, and how a report names
the rule. A language's rules name themselves in its provider (`qa_rules`); the
neutral checks in their own module (`RULES`, where `prefix.*` covers a family).
"""

from __future__ import annotations

from functools import cache

from codelith.apps.qa import designed
from codelith.apps.qa.checks import (
    code,
    dependencies,
    deploy,
    environment,
    flows,
    online,
    review,
    sandbox,
    secrets,
    untested,
)
from codelith.languages import registry


@cache
def _table() -> tuple[dict[str, str], dict[str, str]]:
    exact: dict[str, str] = {}
    families: dict[str, str] = {}
    for module in (code, flows, secrets, deploy, environment, dependencies, online, untested, review, sandbox, designed):
        for rule, label in getattr(module, "RULES", {}).items():
            if rule.endswith(".*"):
                families[rule[:-1]] = label
            else:
                exact[rule] = label
    for provider in registry.providers():
        for rule, label in getattr(provider, "qa_rules", {}).items():
            exact.setdefault(rule, label)
    return exact, families


def label(rule: str) -> str:
    """The rule's short name; a readable form of its id when it has none."""
    exact, families = _table()
    if rule in exact:
        return exact[rule]
    for prefix, name in families.items():
        if rule.startswith(prefix):
            return name
    words = rule.split(".", 1)[-1].replace("-", " ")
    return words[:1].upper() + words[1:]


__all__ = ["label"]
