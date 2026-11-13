"""
One finding, and the fingerprint that recognises it in the next run.

The fingerprint is made from the rule, the file and the code the finding points at,
with its whitespace ignored, and how many identical lines came before it in the same
file. Not the line number: a finding moved by an edit above it is the same finding,
still open, and a dismissal of it still holds.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

_SPACE = re.compile(r"\s+")

#: The most lines a finding quotes.
SNIPPET_LINES = 8


@dataclass(slots=True)
class Finding:
    rule: str
    area: str
    severity: str
    title: str
    message: str
    fix: str
    path: str | None = None
    line: int | None = None
    end_line: int | None = None
    confidence: str = "confirmed"
    #: `rule` (a language's rule), `check` (a neutral one), `tool`, `model`, `test`.
    source: str = "rule"
    snippet: str = ""
    evidence: dict = field(default_factory=dict)
    impact: dict = field(default_factory=dict)
    patch: str | None = None
    fingerprint: str = ""
    is_new: bool = False


def quote(lines: list[str], line: int | None, end_line: int | None) -> str:
    """The lines a finding points at, at most `SNIPPET_LINES` of them."""
    if not line or line < 1 or line > len(lines):
        return ""
    last = min(end_line or line, line + SNIPPET_LINES - 1, len(lines))
    return "\n".join(lines[line - 1 : last])


def fingerprint_all(findings: list[Finding]) -> None:
    """Give each finding its fingerprint, in file order so occurrences count the same way every run."""
    seen: dict[tuple[str, str, str], int] = {}
    for f in sorted(findings, key=lambda f: (f.path or "", f.line or 0, f.rule)):
        anchor = _SPACE.sub("", f.snippet) if f.snippet else f.title
        key = (f.rule, f.path or "", anchor)
        occurrence = seen.get(key, 0)
        seen[key] = occurrence + 1
        raw = f"{f.rule}|{f.path or ''}|{anchor}|{occurrence}"
        f.fingerprint = hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


__all__ = ["SNIPPET_LINES", "Finding", "fingerprint_all", "quote"]
