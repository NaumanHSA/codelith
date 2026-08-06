"""
The digest map that makes staleness exact.

Deliberately not a git diff: uploads and local directories have no commits, and a
per-file content digest works for all of them. These pin the properties the
staleness pass depends on — same content means same digest on any machine, and any
change to a file changes it.
"""

from __future__ import annotations

from app.agents.analysis.structured_extractor import StructuredExtractorAgent
from app.knowledge.builder import SourceFile


def hashes(**files: str) -> dict[str, str]:
    return StructuredExtractorAgent._hashes(
        [SourceFile(path=p, content=c, language="python") for p, c in files.items()]
    )


class TestFileDigests:
    def test_the_same_content_hashes_the_same(self) -> None:
        """A rebuild of an unchanged file must not mark its pages stale."""
        assert hashes(a="x = 1") == hashes(a="x = 1")

    def test_changed_content_changes_the_digest(self) -> None:
        assert hashes(a="x = 1") != hashes(a="x = 2")

    def test_whitespace_counts_as_a_change(self) -> None:
        """It shows up in the prose we quote, so it is a change worth noticing."""
        assert hashes(a="x = 1") != hashes(a="x  = 1")

    def test_every_file_is_recorded(self) -> None:
        assert set(hashes(a="1", b="2")) == {"a", "b"}

    def test_an_empty_file_still_gets_a_digest(self) -> None:
        """Absent from the map means deleted, which is a different fact."""
        assert hashes(a="")["a"]

    def test_digests_are_short(self) -> None:
        """This is a change detector, not a security boundary."""
        assert len(hashes(a="x")["a"]) == 16
