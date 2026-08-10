"""
One thing a tool found, in a shape that does not care which tool found it.

Ruff speaks JSON with `code` and `location.row`; mypy speaks lines of
`path:line: error: message  [rule]`. Downstream — ranking, impact, the UI — must not
know that, or adding a third tool means touching all of it.

**Severity is normalised, and deliberately coarse.** Tools disagree about what
"warning" means and there is no honest mapping between their scales; three levels is
what a reader can act on. Anything a tool calls an error is an error, and everything
else is a warning until something proves otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        """For sorting. Higher is worse."""
        return {Severity.ERROR: 2, Severity.WARNING: 1, Severity.INFO: 0}[self]


@dataclass(frozen=True, slots=True)
class Finding:
    """A tool's output about one place in the code."""

    tool: str
    #: The tool's own identifier — `F821`, `assignment`. Kept verbatim so a reader can
    #: search for it, and so two runs of the same tool are comparable.
    rule: str
    #: Repository-relative, forward slashes. The knowledge base stores paths that way
    #: and every join downstream depends on the two matching.
    path: str
    line: int
    column: int = 0
    message: str = ""
    severity: Severity = Severity.WARNING
    #: Set by Q2. A finding without impact is still a finding — the field is optional
    #: so a graph that is unavailable degrades the answer rather than losing it.
    impact: Impact | None = None

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}"

    def with_impact(self, impact: Impact) -> Finding:
        from dataclasses import replace

        return replace(self, impact=impact)

    def relative_to(self, root: str) -> Finding:
        """The same finding with a repository-relative path.

        Ruff reports absolute paths even when invoked as `.`, and the knowledge base
        stores paths relative to the repository root. Every join in Q2 — the graph, the
        entity index, documentation provenance — matches on that string, so an absolute
        path silently produces a finding with no impact rather than an error.
        """
        from dataclasses import replace

        cleaned = (root or "").replace("\\", "/").rstrip("/")
        if cleaned and self.path.lower().startswith(cleaned.lower() + "/"):
            return replace(self, path=self.path[len(cleaned) + 1 :])
        return self


@dataclass(frozen=True, slots=True)
class Impact:
    """What else a finding touches. Filled in by Q2 from the code graph."""

    #: Files that transitively import the one the finding is in.
    reached_files: int = 0
    #: The nearest few, for a sentence a reader can check.
    reached_sample: tuple[str, ...] = ()
    #: Written documentation pages whose `source_files` include this path.
    documented_in: tuple[str, ...] = ()
    #: The symbol the finding sits inside, when the knowledge base knows it.
    symbol: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.reached_files or self.documented_in or self.symbol)


@dataclass(slots=True)
class ToolReport:
    """What one tool produced, including the reasons it produced nothing.

    A tool that is not installed and a tool that found no problems both return an
    empty list, and they mean opposite things. Conflating them tells a reader their
    code is clean when nothing looked at it.
    """

    tool: str
    findings: list[Finding] = field(default_factory=list)
    #: None when the tool ran. A sentence when it did not, shown to the reader.
    unavailable: str | None = None
    duration_seconds: float = 0.0

    @property
    def ran(self) -> bool:
        return self.unavailable is None


__all__ = ["Finding", "Impact", "Severity", "ToolReport"]
