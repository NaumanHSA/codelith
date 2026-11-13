"""
Small, local fixes as patches.

Some findings have a fix that needs nothing but the line itself: a bare `except:`
becomes `except Exception:`, `verify=False` becomes `verify=True`, `yaml.load(`
becomes `yaml.safe_load(`. For those QA writes the change as a unified diff a person
can read in the diff viewer and `git apply` as it is. Nothing here edits the
repository.

A fix is only written when the rewrite is certain to be what the rule asks for and
leaves the line valid; anything that needs to know more than the line (a mutable
default, a secret moved to the environment) keeps its written advice instead.

When the sandbox ran, every patch is applied to the throwaway copy and the tests run
again (`checks/sandbox.py`): a fix after which no test newly fails says so.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from pathlib import Path

from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding

_LITERAL = r"(?=(?:[rbuf]{0,2}['\"]|-?\d))"
_REQUESTS_CALL = re.compile(r"\b(?:requests|httpx)\.(?:get|post|put|patch|delete|head|options|request)\(")


def _sub(pattern: str, repl: str, flags: int = 0) -> Callable[[str], str | None]:
    compiled = re.compile(pattern, flags)

    def fix(line: str) -> str | None:
        new = compiled.sub(repl, line, count=1)
        return new if new != line else None

    return fix


def _is_literal(line: str) -> str | None:
    new = re.sub(rf"\bis\s+not\s+{_LITERAL}", "!= ", line)
    new = re.sub(rf"\bis\s+{_LITERAL}", "== ", new)
    return new if new != line else None


def _yaml_load(line: str) -> str | None:
    if "Loader" in line or "yaml.load(" not in line:
        return None
    return line.replace("yaml.load(", "yaml.safe_load(", 1)


def _timeout(line: str) -> str | None:
    """`timeout=30` added to a requests/httpx call that opens and closes on this line."""
    m = _REQUESTS_CALL.search(line)
    if not m:
        return None
    depth, i = 1, m.end()
    quote: str | None = None
    while i < len(line) and depth:
        ch = line[i]
        if quote:
            if ch == quote and line[i - 1] != "\\":
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    if depth or "timeout" in line[m.start() : i]:
        return None
    close = i - 1
    inside = line[m.end() : close].strip()
    return line[:close] + (", timeout=30" if inside else "timeout=30") + line[close:]


#: The rules with a fix of their own, and the rewrite of the flagged line.
FIXES: dict[str, Callable[[str], str | None]] = {
    "py.bare-except": _sub(r"\bexcept\s*:", "except Exception:"),
    "py.is-literal": _is_literal,
    "py.debug-on": _sub(r"\b(debug|DEBUG)(\s*=\s*)True\b", r"\1\2False"),
    "py.tls-off": _sub(r"\bverify(\s*=\s*)False\b", r"verify\1True"),
    "py.unsafe-deserialization": _yaml_load,
    "py.weak-hash": _sub(r"\bhashlib\.(md5|sha1)\(", "hashlib.sha256("),
    "py.no-timeout": _timeout,
    "ts.tls-off": _sub(r"\brejectUnauthorized(\s*:\s*)false\b", r"rejectUnauthorized\1true"),
    "go.tls-off": _sub(r"\bInsecureSkipVerify(\s*:\s*)true\b", r"InsecureSkipVerify\1false"),
}

#: What each fix changes, said beside the patch.
NOTES: dict[str, str] = {
    "py.weak-hash": "Values hashed before the change will not match: re-hash anything stored.",
    "py.no-timeout": "30 seconds is a starting point; pick what the call can really take.",
    "py.bare-except": "Narrower still is better: catch the exceptions this code expects.",
}


def unified(path: str, before: list[str], after: list[str]) -> str:
    """A unified diff of two versions of one file, with real line numbers."""
    return "".join(
        difflib.unified_diff(
            [line + "\n" for line in before],
            [line + "\n" for line in after],
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )


def patch_for(rule: str, path: str, lines: list[str], line: int | None) -> str | None:
    """The patch fixing this rule at this line, when the rule has a fix and it applies."""
    fixer = FIXES.get(rule)
    if fixer is None or not line or not 0 < line <= len(lines):
        return None
    new = fixer(lines[line - 1])
    if new is None:
        return None
    after = list(lines)
    after[line - 1] = new
    return unified(path, lines, after)


async def attach(ctx: RunContext, found: list[Finding]) -> int:
    """Give each finding that has a mechanical fix its patch. Returns how many got one."""
    n = 0
    for f in found:
        if f.patch or not f.path or f.rule not in FIXES:
            continue
        patch = patch_for(f.rule, f.path, await ctx.lines(f.path), f.line)
        if patch:
            f.patch = patch
            f.evidence["fix"] = "mechanical"
            if f.rule in NOTES:
                f.evidence["fix_note"] = NOTES[f.rule]
            n += 1
    return n


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def apply(text: str, patch: str) -> str | None:
    """
    `text` with a one-file unified diff applied, or None when it does not apply as
    written (the lines it expects are not there). No fuzz: a patch checked against
    tests must be the patch shown.
    """
    lines = text.split("\n")
    trailing = lines[-1] == ""
    if trailing:
        lines.pop()
    out: list[str] = []
    at = 0  # next unread line of `lines`, 0-based
    hunk_lines: list[str] = []
    start = None

    def flush() -> bool:
        nonlocal at
        if start is None:
            return True
        if start < at:
            return False
        out.extend(lines[at:start])
        at = start
        for raw in hunk_lines:
            if raw.startswith("\\"):
                continue
            tag, body = raw[:1], raw[1:]
            if tag in (" ", "-"):
                if at >= len(lines) or lines[at] != body:
                    return False
                at += 1
                if tag == " ":
                    out.append(body)
            elif tag == "+":
                out.append(body)
        return True

    for raw in patch.splitlines():
        if raw.startswith(("--- ", "+++ ")):
            continue
        m = _HUNK.match(raw)
        if m:
            if not flush():
                return None
            old_start, old_len = int(m.group(1)), int(m.group(2) or 1)
            start = old_start - 1 if old_len else old_start
            hunk_lines = []
        elif start is not None:
            hunk_lines.append(raw)
    if not flush():
        return None
    out.extend(lines[at:])
    return "\n".join(out) + ("\n" if trailing else "")


def apply_to(root: Path, f: Finding) -> str | None:
    """Apply a finding's patch to its file under `root`. Returns the file's old text, or None."""
    if not f.patch or not f.path:
        return None
    target = root / f.path
    if not target.is_file():
        return None
    before = target.read_text(encoding="utf-8", errors="replace")
    after = apply(before, f.patch)
    if after is None:
        return None
    target.write_text(after, encoding="utf-8")
    return before


__all__ = ["FIXES", "apply", "apply_to", "attach", "patch_for", "unified"]
