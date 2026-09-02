"""
Two audiences, one command.

A person reading a terminal and a script parsing stdout want opposite things, and
the usual mistake is to serve the second badly by decorating the first. Every
command takes `--json` and, when it is set, prints exactly one JSON document to
stdout and nothing else — progress, spinners and colour all go to stderr or are
suppressed, so `codelith status --json | jq` is never surprised by a spinner.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console


def _force_utf8() -> None:
    """
    Make the streams speak UTF-8 before anything is written to them.

    The output uses `▸`, `·` and em-dashes, and rich truncates with `…`. On Windows
    the console defaults to cp1252, which cannot encode any of them — the first run
    of `codelith status` printed a replacement character in every truncated cell.
    Reconfiguring is safe everywhere: on a stream that is already UTF-8 it is a no-op,
    and `errors="replace"` means a console that genuinely cannot render a glyph
    degrades instead of raising mid-command.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):  # pragma: no cover - redirected or closed
                pass


_force_utf8()

#: Human output on stdout, progress and diagnostics on stderr. The split is what
#: lets `--json` stay clean without a second code path in every command.
out = Console()
err = Console(stderr=True)


class Output:
    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json

    def result(self, payload: Any) -> None:
        """The one thing the command was asked for."""
        if self.as_json:
            sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")

    def say(self, markup: str) -> None:
        """Prose for a person. Silent under `--json`."""
        if not self.as_json:
            out.print(markup)

    def step(self, markup: str) -> None:
        """Progress. Always stderr, so it never lands in a piped document."""
        if not self.as_json:
            err.print(markup)

    def warn(self, markup: str) -> None:
        err.print(f"[yellow]{markup}[/yellow]")

    def fail(self, markup: str) -> None:
        err.print(f"[red]{markup}[/red]")


def humanise_seconds(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60:02d}s"
