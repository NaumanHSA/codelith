"""
The tools Codelith runs, and how to read what they say.

**Codelith does not reimplement any of this.** Ruff and mypy are deterministic, fast,
free, and better at finding these problems than a model. The value added here is the
next phase — what each finding *touches* — and that only works if the findings
themselves are real.

**QA maps language to tools, not the `LanguageProvider`.** Adding a `qa_tools()` method
to the provider would put this app's vocabulary in the base, where every other app and
every future language would inherit it. The provider already answers the only question
needed: what language is this file. The choice of linter is QA's business.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

import structlog

from codelith.apps.qa.findings import Finding, Severity
from codelith.languages.registry import DEFAULT_IGNORED_DIRS

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    #: Run from the repository root. `.` rather than a file list: the tools are far
    #: faster walking the tree themselves, and a list long enough to matter overflows
    #: the command line on Windows.
    command: tuple[str, ...]
    parse: Callable[[str, str], list[Finding]]
    #: What a reader loses when it is not installed.
    provides: str


# ── ruff ──────────────────────────────────────────────────────────────────────

def parse_ruff(stdout: str, _stderr: str) -> list[Finding]:
    """
    Ruff's JSON. One object per diagnostic, with `location.row` 1-based.

    Everything is a warning except the `E9`/`F82` families — syntax errors and
    undefined names, which do not merely smell wrong, they break at runtime. That
    distinction is what made `F821` worth catching: it broke every documentation job.
    """
    try:
        rows = json.loads(stdout or "[]")
    except json.JSONDecodeError:
        logger.warning("qa_ruff_unparseable", head=stdout[:120])
        return []

    findings: list[Finding] = []
    for row in rows if isinstance(rows, list) else []:
        code = str(row.get("code") or "")
        location = row.get("location") or {}
        findings.append(
            Finding(
                tool="ruff",
                rule=code,
                path=_normalise(row.get("filename") or ""),
                line=int(location.get("row") or 1),
                column=int(location.get("column") or 0),
                message=str(row.get("message") or ""),
                severity=(
                    Severity.ERROR
                    if code.startswith(("E9", "F82", "F81"))
                    else Severity.WARNING
                ),
            )
        )
    return findings


# ── mypy ──────────────────────────────────────────────────────────────────────

#: `path:line: error: message  [rule]` — column is present only with `--show-column`.
_MYPY_LINE = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*"
    r"(?P<level>error|warning|note):\s*(?P<message>.*?)"
    r"(?:\s+\[(?P<rule>[\w-]+)\])?$"
)


def parse_mypy(stdout: str, _stderr: str) -> list[Finding]:
    """
    Mypy's text output, line by line.

    `note:` lines are continuations of the diagnostic above them, not findings of
    their own — emitting them separately would triple the count and bury the errors.
    """
    findings: list[Finding] = []
    for raw in (stdout or "").splitlines():
        match = _MYPY_LINE.match(raw.strip())
        if not match or match.group("level") == "note":
            continue
        findings.append(
            Finding(
                tool="mypy",
                rule=match.group("rule") or "type",
                path=_normalise(match.group("path")),
                line=int(match.group("line")),
                column=int(match.group("col") or 0),
                message=match.group("message").strip(),
                severity=(
                    Severity.ERROR if match.group("level") == "error" else Severity.WARNING
                ),
            )
        )
    return findings


def _normalise(path: str) -> str:
    """Repository-relative, forward slashes — the shape the knowledge base stores.

    Every join in Q2 depends on these matching, and a Windows checkout hands back
    backslashes and sometimes a leading `./`.
    """
    cleaned = (path or "").replace("\\", "/").lstrip("./")
    return cleaned


# ── what applies to what ──────────────────────────────────────────────────────

#: Directories that are never the repository's own source.
#:
#: Reused from the base rather than restated: analysis already decided what is not
#: code, and two lists would drift. Codelith's own tree makes the case — it keeps
#: `repos/` and `runs/` for clones and job artifacts, and mypy walking into them found
#: four copies of the same analysed project and gave up with "duplicate module".
_SKIP = sorted(DEFAULT_IGNORED_DIRS | {"repos", "runs", "site-packages"})

#: One regex for tools that take one.
_SKIP_RE = r"(^|/)(" + "|".join(re.escape(d) for d in _SKIP) + r")/"

RUFF = ToolSpec(
    name="ruff",
    command=(
        "ruff", "check", "--output-format", "json", "--exit-zero",
        # Ruff respects the repository's own config when it has one; these are the
        # floor for a checkout that does not.
        *(arg for d in _SKIP for arg in ("--exclude", d)),
        ".",
    ),
    parse=parse_ruff,
    provides="undefined names, unused imports, and style problems",
)

MYPY = ToolSpec(
    name="mypy",
    # `--ignore-missing-imports` because a checkout has no virtualenv: without it every
    # third-party import is an error and the real findings are buried thousands deep.
    command=(
        "mypy", ".", "--no-error-summary", "--no-color-output",
        "--ignore-missing-imports", "--show-column-numbers",
        "--exclude", _SKIP_RE,
    ),
    parse=parse_mypy,
    provides="type errors",
)

#: Language → the tools worth running on it. A Go repository must never be run through
#: ruff: it produces nothing, takes time, and reads to a user as "no problems found".
TOOLS_BY_LANGUAGE: dict[str, tuple[ToolSpec, ...]] = {
    "python": (RUFF, MYPY),
}


def tools_for(languages: list[str]) -> list[ToolSpec]:
    """The tools that apply to a codebase, in a stable order and without duplicates."""
    chosen: list[ToolSpec] = []
    for language in languages:
        for spec in TOOLS_BY_LANGUAGE.get((language or "").lower(), ()):
            if spec not in chosen:
                chosen.append(spec)
    return chosen


__all__ = ["MYPY", "RUFF", "TOOLS_BY_LANGUAGE", "ToolSpec", "parse_mypy", "parse_ruff", "tools_for"]
