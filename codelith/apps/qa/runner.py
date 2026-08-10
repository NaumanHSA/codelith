"""
Running somebody else's tool without letting it take the process down with it.

Three failure modes, all ordinary, none of which may raise: the tool is not installed,
the tool hangs, the tool exits non-zero. The third is not a failure at all — ruff exits
1 precisely when it has something to say — so exit codes are data here, not errors.

**A timeout is not optional.** mypy on a large repository can run for minutes, and a
QA request that never returns is worse than one that returns "this took too long".
"""

from __future__ import annotations

import asyncio
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

#: Generous, because these are whole-repository passes, and bounded, because the caller
#: is a web request that somebody is waiting on.
DEFAULT_TIMEOUT = 180.0


@dataclass(slots=True)
class ToolResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_seconds: float = 0.0
    #: A sentence when the tool could not be run at all. `None` means it ran, whatever
    #: it exited with.
    unavailable: str | None = None

    @property
    def ran(self) -> bool:
        return self.unavailable is None


async def run_tool(
    command: list[str],
    cwd: Path,
    timeout: float = DEFAULT_TIMEOUT,
) -> ToolResult:
    """
    Run one command in `cwd` and bring back what it said.

    Never raises. A caller that has to wrap this in `try` has to decide what an
    exception means about the codebase, and the answer is nothing — a missing linter
    is a fact about the machine.
    """
    if not command:
        return ToolResult(unavailable="No command given.")

    executable = shutil.which(command[0])
    if executable is None:
        return ToolResult(
            unavailable=(
                f"`{command[0]}` is not installed on this machine, so nothing was "
                f"checked with it. Install it to see these findings."
            )
        )

    started = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            *command[1:],
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:  # pragma: no cover - defensive
        return ToolResult(unavailable=f"`{command[0]}` could not be started: {exc}")

    try:
        raw_out, raw_err = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        # Killed, then reaped. An abandoned process holds the checkout directory open
        # and the cleanup that follows would fail on Windows.
        process.kill()
        try:
            await process.communicate()
        except Exception:  # pragma: no cover - the process is already gone
            pass
        logger.warning("qa_tool_timeout", tool=command[0], seconds=timeout)
        return ToolResult(
            duration_seconds=time.monotonic() - started,
            unavailable=f"`{command[0]}` did not finish within {timeout:.0f}s.",
        )

    return ToolResult(
        stdout=raw_out.decode("utf-8", errors="replace"),
        stderr=raw_err.decode("utf-8", errors="replace"),
        exit_code=process.returncode or 0,
        duration_seconds=time.monotonic() - started,
    )


__all__ = ["DEFAULT_TIMEOUT", "ToolResult", "run_tool"]
