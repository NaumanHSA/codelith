"""
Mermaid validation.

Run 2 published neither of the two diagrams it generated, and neither would have
rendered if it had: one ended in `style graph { node fill #4a4a4a }`, the other opened
with the literal text `mermaid diagram:` and drew an ASCII tree of `|-->` lines. The
only cleaning in the pipeline stripped code fences, so nothing ever noticed.

There is no Mermaid parser in Python, and shelling out to the JS one would break the
"no external network, no extra services" property. This is a structural check instead:
it verifies the diagram declares a known type, that its body uses syntax belonging to
that type, and that it has content — which is enough to reject everything that has
actually gone wrong, without pretending to be a grammar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Diagram types we ask for, mapped to a pattern the body must match at least once.
#: Anchored to the constructs each type is built from, so a sequence diagram made of
#: flowchart arrows is rejected rather than published.
_DIAGRAM_TYPES: dict[str, re.Pattern[str]] = {
    "graph": re.compile(r"(-->|---|-\.->|==>)"),
    "flowchart": re.compile(r"(-->|---|-\.->|==>)"),
    "sequencediagram": re.compile(r"(->>|-->>|->|-->)"),
    # `--` alone is too weak: `class Foo --` followed by free text passed the check
    # and would have rendered as garbage. Require a real relationship arrow or a
    # member block.
    "classdiagram": re.compile(r"(<\|--|\*--|o--|-->|\.\.>|\|>|\{)"),
    "erdiagram": re.compile(r"(\|\|--|\}o--|\|\|\.\.|\}\|--)"),
    "statediagram": re.compile(r"(-->|\[\*\])"),
    "statediagram-v2": re.compile(r"(-->|\[\*\])"),
    "gantt": re.compile(r"(section|:)"),
    "journey": re.compile(r"(section|:)"),
    "pie": re.compile(r'".*"\s*:\s*\d'),
    "mindmap": re.compile(r"\S"),
}

#: Constructs that are not Mermaid and have shown up in real output.
_FORBIDDEN = (
    (re.compile(r"^\s*\|--"), "ASCII tree branches (`|--`) are not Mermaid"),
    (re.compile(r"\bstyle\s+\w+\s*\{"), "CSS-style blocks are not Mermaid"),
    (re.compile(r"--\w+->"), "arrows may not carry inline modifiers"),
    (re.compile(r"--style\b"), "`--style` is not Mermaid"),
    # Produced live: `class Foo --` opening a block of indented free text. The file
    # also carried valid `-->` relations further down, so a whole-document check
    # passed it while the class declarations themselves were nonsense.
    (re.compile(r"^\s*class\s+\S+\s*--\s*$"), "class declaration ends in a dangling `--`"),
)


@dataclass(slots=True)
class MermaidCheck:
    ok: bool
    reason: str = ""


def clean_mermaid(raw: str) -> str:
    """Strip fences, language tags and conversational preamble around a diagram."""
    text = (raw or "").strip()

    if "```" in text:
        parts = text.split("```")
        # Prefer the first fenced block that looks like a diagram.
        for part in parts[1:]:
            body = part[len("mermaid"):] if part.lstrip().startswith("mermaid") else part
            if _first_keyword(body):
                text = body.strip()
                break
        else:
            text = parts[1] if len(parts) > 1 else text
            if text.lstrip().startswith("mermaid"):
                text = text.lstrip()[len("mermaid"):]

    lines = text.strip().splitlines()
    # Drop anything before the type declaration — models like to introduce themselves.
    for index, line in enumerate(lines):
        if _first_keyword(line):
            return "\n".join(lines[index:]).strip()
    return "\n".join(lines).strip()


def validate_mermaid(diagram: str) -> MermaidCheck:
    """Structural check. Cheap, conservative, and never raises."""
    text = (diagram or "").strip()
    if not text:
        return MermaidCheck(False, "empty diagram")

    keyword = _first_keyword(text)
    if not keyword:
        first = text.splitlines()[0][:60]
        return MermaidCheck(False, f"no diagram type declared (starts with {first!r})")

    body = "\n".join(text.splitlines()[1:]).strip()
    if not body:
        return MermaidCheck(False, f"{keyword} declared but has no body")

    for pattern, reason in _FORBIDDEN:
        if any(pattern.search(line) for line in text.splitlines()):
            return MermaidCheck(False, reason)

    expected = _DIAGRAM_TYPES[keyword]
    if not expected.search(body):
        return MermaidCheck(False, f"{keyword} body contains no {keyword} syntax")

    return MermaidCheck(True)


def _first_keyword(text: str) -> str | None:
    """The declared diagram type, if the text opens with one."""
    for line in text.strip().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        head = stripped.split()[0].rstrip(";").lower()
        if head in _DIAGRAM_TYPES:
            return head
        # `graph TD` / `flowchart LR` put the direction on the same token boundary.
        return head if head in _DIAGRAM_TYPES else None
    return None


__all__ = ["MermaidCheck", "clean_mermaid", "validate_mermaid"]
