"""
What QA derives for itself.

Q2 discovered the need rather than assuming it. The knowledge base stores symbols per
*module*, and a module is usually several files, so a finding at `config/mcp.py:127`
could not be attributed — the symbol list for `neurosurfer.config` might be from any of
its files. On neurosurfer that made attribution possible for almost nothing.

Adding file attribution to the shared analysis would make every project pay for
something only QA reads. So QA parses the checkout it already has, and the sentence
completes: *in `McpStore.enabled` · 24 files reach it*.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from codelith.apps.qa.deep import build_index


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


class TestWhatItKnows:
    def test_a_line_inside_a_function_is_attributed(self, tmp_path: Path) -> None:
        _write(tmp_path, "a.py", """
            def first():
                x = 1
                return x
        """)

        index = build_index(tmp_path)

        assert index.symbol_at("a.py", 3) == "first"

    def test_a_method_carries_its_class(self, tmp_path: Path) -> None:
        """`enabled` says nothing. `McpStore.enabled` says where to look."""
        _write(tmp_path, "a.py", """
            class McpStore:
                def enabled(self):
                    return True
        """)

        index = build_index(tmp_path)

        assert index.symbol_at("a.py", 4) == "McpStore.enabled"

    def test_the_innermost_symbol_wins(self, tmp_path: Path) -> None:
        """A method's line is inside both the method and the class. The method is
        what a reader wants to be told."""
        _write(tmp_path, "a.py", """
            class Outer:
                def inner(self):
                    return 1
        """)

        index = build_index(tmp_path)

        assert index.symbol_at("a.py", 4) == "Outer.inner"

    def test_a_line_after_a_function_is_not_inside_it(self, tmp_path: Path) -> None:
        """**The reason this phase exists.** The knowledge base records only where a
        symbol starts, so it cannot tell a line inside a function from one in the gap
        after it — and would attribute module-level code to the function above."""
        _write(tmp_path, "a.py", """
            def first():
                return 1


            CONSTANT = 2
        """)

        index = build_index(tmp_path)

        assert index.symbol_at("a.py", 3) == "first"
        assert index.symbol_at("a.py", 6) is None

    def test_module_level_code_is_inside_nothing(self, tmp_path: Path) -> None:
        _write(tmp_path, "a.py", "import os\n\ndef f():\n    pass\n")

        assert build_index(tmp_path).symbol_at("a.py", 1) is None

    def test_an_async_function_counts(self, tmp_path: Path) -> None:
        _write(tmp_path, "a.py", """
            async def fetch():
                return 1
        """)

        assert build_index(tmp_path).symbol_at("a.py", 3) == "fetch"


class TestItDoesNotFail:
    def test_an_unparseable_file_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        """A repository with one broken file still deserves the other nine hundred."""
        _write(tmp_path, "broken.py", "def (((")
        _write(tmp_path, "fine.py", "def ok():\n    pass\n")

        index = build_index(tmp_path)

        assert index.files_failed == 1
        assert index.symbol_at("fine.py", 2) == "ok"

    def test_ignored_directories_are_not_walked(self, tmp_path: Path) -> None:
        """A checkout with a `.venv` would otherwise index the whole of site-packages,
        and every finding would resolve to somebody else's code."""
        _write(tmp_path, ".venv/lib/thing.py", "def vendored():\n    pass\n")
        _write(tmp_path, "mine.py", "def mine():\n    pass\n")

        index = build_index(tmp_path)

        assert "mine.py" in index.symbols
        assert not any(".venv" in path for path in index.symbols)

    def test_an_unknown_file_returns_none(self, tmp_path: Path) -> None:
        assert build_index(tmp_path).symbol_at("never-seen.py", 1) is None

    def test_the_commit_is_recorded(self, tmp_path: Path) -> None:
        """The index is only valid for the tree it was built from, so it carries the
        commit it belongs to."""
        assert build_index(tmp_path, commit_sha="abc123").commit_sha == "abc123"
