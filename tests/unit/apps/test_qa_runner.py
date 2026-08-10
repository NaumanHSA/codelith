"""
Running somebody else's tool without letting it take the process down.

Three ordinary failure modes, none of which may raise: the tool is not installed, the
tool hangs, the tool exits non-zero. The third is not a failure — ruff exits 1 exactly
when it has something to say — so an implementation that treats exit codes as errors
reports a clean codebase as broken and a broken one as clean.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from codelith.apps.qa.runner import run_tool


class TestItRuns:
    async def test_stdout_comes_back(self, tmp_path: Path) -> None:
        result = await run_tool([sys.executable, "-c", "print('hello')"], cwd=tmp_path)

        assert result.ran
        assert "hello" in result.stdout
        assert result.exit_code == 0

    async def test_a_non_zero_exit_is_data_not_an_error(self, tmp_path: Path) -> None:
        """The load-bearing one. Ruff exits 1 precisely when it found something, so a
        runner that treats that as failure discards every finding it was asked for."""
        result = await run_tool(
            [sys.executable, "-c", "import sys; print('found it'); sys.exit(1)"],
            cwd=tmp_path,
        )

        assert result.ran
        assert result.exit_code == 1
        assert "found it" in result.stdout

    async def test_it_runs_where_it_was_told(self, tmp_path: Path) -> None:
        """Both tools are invoked as `.` — the working directory *is* the argument."""
        result = await run_tool(
            [sys.executable, "-c", "import os; print(os.getcwd())"], cwd=tmp_path
        )

        assert str(tmp_path.resolve()).lower() in result.stdout.strip().lower()


class TestItDoesNotRaise:
    async def test_a_missing_tool_is_reported(self, tmp_path: Path) -> None:
        result = await run_tool(["definitely-not-a-real-tool-xyz"], cwd=tmp_path)

        assert not result.ran
        assert "not installed" in result.unavailable

    async def test_an_empty_command_is_reported(self, tmp_path: Path) -> None:
        result = await run_tool([], cwd=tmp_path)

        assert not result.ran

    async def test_a_hang_is_cut_off(self, tmp_path: Path) -> None:
        """mypy on a large repository runs for minutes. A QA request that never
        returns is worse than one that says it took too long."""
        result = await run_tool(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            timeout=1.0,
        )

        assert not result.ran
        assert "did not finish" in result.unavailable

    async def test_a_timed_out_process_is_not_left_running(self, tmp_path: Path) -> None:
        """An abandoned process keeps the checkout directory open, and the cleanup
        that follows fails on Windows."""
        marker = tmp_path / "still-alive.txt"
        script = (
            "import time, pathlib, sys\n"
            f"time.sleep(5)\n"
            f"pathlib.Path(r'{marker}').write_text('x')\n"
        )

        await run_tool([sys.executable, "-c", script], cwd=tmp_path, timeout=0.5)
        # Long enough that the script would have written had it survived.
        import asyncio

        await asyncio.sleep(1.5)

        assert not marker.exists(), "the process outlived its timeout"

    async def test_binary_garbage_does_not_crash_the_decode(self, tmp_path: Path) -> None:
        result = await run_tool(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff\\xfe')"],
            cwd=tmp_path,
        )

        assert result.ran
