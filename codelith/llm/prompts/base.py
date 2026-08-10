"""
The prompt template.

`string.Template` with one guard bolted on, and the guard earns its place. A
placeholder that abuts the next word — `"$already_written" "Context:"` across two
adjacent string literals — parses as the single identifier
`already_writtenContext`, which no caller supplies, so `safe_substitute` leaves it
alone and the model is shown the literal text `$already_writtenContext`. That is
exactly what happened to `SECTION_WRITE`: the "do not duplicate the other sections"
instruction never reached a single writer call, silently, for the whole life of the
prompt.

Nothing in the rendered output can be inspected for this — the substituted *values*
routinely contain `$` (source excerpts, shell snippets), so scanning the result would
false-positive. The identifiers in the template text are compared against the keys
the caller passed instead, which is exact.
"""

from __future__ import annotations

from string import Template


class MissingPromptValue(KeyError):
    """A template placeholder no caller supplied — a typo, or an abutting word."""

    def __init__(self, part: str, missing: set[str]) -> None:
        names = ", ".join(sorted(missing))
        super().__init__(
            f"prompt {part} references {names}, which was not supplied. "
            "If a placeholder is followed directly by more text, brace it: ${name}."
        )


class PromptTemplate:
    def __init__(self, system: str, user: str) -> None:
        self._system = system
        self._user = user

    def render(self, **kwargs) -> list[dict]:
        return [
            {"role": "system", "content": self._render(self._system, "system", kwargs)},
            {"role": "user", "content": self._render(self._user, "user", kwargs)},
        ]

    @staticmethod
    def _render(text: str, part: str, values: dict) -> str:
        template = Template(text)
        if missing := set(template.get_identifiers()) - set(values):
            raise MissingPromptValue(part, missing)
        return template.safe_substitute(**values)


__all__ = ["PromptTemplate", "MissingPromptValue"]
