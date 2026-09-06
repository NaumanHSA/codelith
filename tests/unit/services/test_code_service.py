"""
Rebuilding a file from the chunks that outlived the clone.

Analysis discards the checkout, so `code_chunks` is the only copy of any source and
this function is the only thing standing between a reader and a plausible-looking
lie. The chunks overlap in places and leave holes in others: measured on this
machine, `src/loop/livenessLoop.js` is 252 lines whose chunks cover 423, and
`src/draw/hole.js` has thirteen separate runs of lines nothing claims.

The property that matters is not "it produces text". It is that **no line ever
appears in the wrong place**, and that a hole is reported as a hole rather than
closed by sliding the next chunk up against the last.
"""

from __future__ import annotations

import pytest

from codelith.services.code_service import rebuild


class Chunk:
    """A `CodeChunk` reduced to the three fields the rebuild reads."""

    def __init__(self, start: int | None, end: int | None, content: str):
        self.start_line = start
        self.end_line = end
        self.content = content


def text_of(segments) -> str:
    return "\n".join(s.text for s in segments if s.kind == "code")


def shape(segments) -> list[tuple[str, int, int]]:
    return [(s.kind, s.start, s.end) for s in segments]


class TestTheOrdinaryCase:
    def test_two_chunks_that_meet(self):
        segments, indexed, missing = rebuild(
            [Chunk(1, 2, "one\ntwo"), Chunk(3, 4, "three\nfour")]
        )
        assert shape(segments) == [("code", 1, 4)]
        assert text_of(segments) == "one\ntwo\nthree\nfour"
        assert (indexed, missing) == (4, 0)

    def test_one_chunk(self):
        segments, indexed, missing = rebuild([Chunk(1, 1, "only")])
        assert shape(segments) == [("code", 1, 1)]
        assert (indexed, missing) == (1, 0)

    def test_nothing_at_all(self):
        """A file analysis saw and kept nothing of."""
        assert rebuild([]) == ([], 0, 0)


class TestOverlap:
    """
    Chunks overlap by design. Every overlap measured agrees exactly on the shared
    lines, so the rule only has to be deterministic - but it must never double a
    line, which is what concatenating chunks would do.
    """

    def test_an_overlap_is_not_repeated(self):
        segments, indexed, missing = rebuild(
            [Chunk(1, 3, "a\nb\nc"), Chunk(2, 4, "b\nc\nd")]
        )
        assert text_of(segments) == "a\nb\nc\nd"
        assert (indexed, missing) == (4, 0)

    def test_a_chunk_wholly_inside_another(self):
        """`livenessLoop.js` has one: 57-73 sits inside 14-129."""
        segments, _, _ = rebuild([Chunk(1, 6, "a\nb\nc\nd\ne\nf"), Chunk(3, 4, "c\nd")])
        assert text_of(segments) == "a\nb\nc\nd\ne\nf"

    def test_first_writer_wins(self):
        """Deterministic, which is all that is asked of it: real overlaps agree."""
        segments, _, _ = rebuild([Chunk(1, 1, "first"), Chunk(1, 1, "second")])
        assert text_of(segments) == "first"


class TestGapsAreNamedNotClosed:
    def test_a_hole_becomes_its_own_segment(self):
        """
        The whole reason segments exist. Joining 1-2 onto 5-6 would show line 5
        directly under line 2 and a reader would believe it.
        """
        segments, indexed, missing = rebuild([Chunk(1, 2, "a\nb"), Chunk(5, 6, "e\nf")])
        assert shape(segments) == [("code", 1, 2), ("gap", 3, 4), ("code", 5, 6)]
        assert (indexed, missing) == (4, 2)

    def test_a_gap_carries_no_text(self):
        segments, _, _ = rebuild([Chunk(1, 1, "a"), Chunk(3, 3, "c")])
        assert [s.text for s in segments if s.kind == "gap"] == [""]

    def test_a_file_that_does_not_start_at_line_one(self):
        segments, indexed, missing = rebuild([Chunk(4, 5, "d\ne")])
        assert shape(segments) == [("gap", 1, 3), ("code", 4, 5)]
        assert (indexed, missing) == (2, 3)

    def test_several_holes(self):
        """`hole.js` has thirteen. They must not merge into one."""
        segments, _, missing = rebuild(
            [Chunk(1, 1, "a"), Chunk(3, 3, "c"), Chunk(6, 6, "f")]
        )
        assert shape(segments) == [
            ("code", 1, 1), ("gap", 2, 2), ("code", 3, 3),
            ("gap", 4, 5), ("code", 6, 6),
        ]
        assert missing == 3


class TestTheTail:
    """
    The end of a file is the part a reader most readily assumes they have all of.
    `livenessLoop.js` is 252 lines and its chunks stop at 251.
    """

    def test_lines_past_the_last_chunk_are_reported(self):
        segments, indexed, missing = rebuild([Chunk(1, 2, "a\nb")], loc=5)
        assert shape(segments) == [("code", 1, 2), ("gap", 3, 5)]
        assert (indexed, missing) == (2, 3)

    def test_loc_smaller_than_the_chunks_is_ignored(self):
        """The parser's count is a hint, not the authority. Content wins."""
        segments, indexed, _ = rebuild([Chunk(1, 4, "a\nb\nc\nd")], loc=2)
        assert shape(segments) == [("code", 1, 4)]
        assert indexed == 4

    def test_no_loc_means_no_invented_tail(self):
        segments, _, missing = rebuild([Chunk(1, 2, "a\nb")])
        assert shape(segments) == [("code", 1, 2)]
        assert missing == 0


class TestChunksThatLieAboutThemselves:
    def test_content_longer_than_the_span_is_clamped(self):
        """
        The guard that keeps a malformed chunk from overwriting the next region with
        a copy of itself. Every `code` chunk measured agrees with its span, so this
        costs nothing today and is the difference between a wrong file and a gap on
        the day one does not.
        """
        segments, indexed, _ = rebuild([Chunk(1, 2, "a\nb\nSTRAY\nSTRAY")])
        assert text_of(segments) == "a\nb"
        assert indexed == 2

    def test_content_shorter_than_the_span_leaves_a_gap(self):
        """
        The docstring shape, which is why `chunks_for_file` excludes them: a span of
        62-75 holding two lines. Excluded at the query, but if one ever arrives here
        the missing lines must read as missing rather than as the next chunk.
        """
        segments, indexed, missing = rebuild([Chunk(1, 5, "a\nb"), Chunk(6, 6, "f")])
        assert shape(segments) == [("code", 1, 2), ("gap", 3, 5), ("code", 6, 6)]
        assert (indexed, missing) == (3, 3)

    def test_a_chunk_with_no_start_line_is_skipped(self):
        segments, indexed, _ = rebuild([Chunk(None, None, "nowhere"), Chunk(1, 1, "a")])
        assert text_of(segments) == "a"
        assert indexed == 1

    def test_a_chunk_with_no_end_line_uses_its_own_length(self):
        segments, indexed, _ = rebuild([Chunk(1, None, "a\nb\nc")])
        assert shape(segments) == [("code", 1, 3)]
        assert indexed == 3

    def test_an_empty_chunk_contributes_nothing(self):
        segments, indexed, _ = rebuild([Chunk(1, 1, ""), Chunk(2, 2, "b")])
        assert shape(segments) == [("gap", 1, 1), ("code", 2, 2)]
        assert indexed == 1


class TestBlankLinesSurvive:
    """
    A blank line inside a chunk is content and must be kept: dropping it shifts every
    line after it, and the numbers down the gutter would then be wrong rather than
    merely incomplete.
    """

    def test_an_interior_blank_line_keeps_its_number(self):
        segments, indexed, missing = rebuild([Chunk(1, 3, "a\n\nc")])
        assert shape(segments) == [("code", 1, 3)]
        assert segments[0].text == "a\n\nc"
        assert (indexed, missing) == (3, 0)

    @pytest.mark.parametrize("body", ["a\n\n\nd", "\n\nc", "a\n\nc"])
    def test_line_numbering_matches_the_content(self, body):
        lines = body.splitlines()
        segments, _, _ = rebuild([Chunk(1, len(lines), body)])
        code = [s for s in segments if s.kind == "code"]
        assert code[0].text.splitlines() == lines

    def test_a_chunk_ending_in_a_newline_reports_a_gap_not_a_phantom_line(self):
        """
        `"a\n\n".splitlines()` is two lines, not three: a trailing newline ends the
        last line rather than starting another. So a chunk claiming 1-3 whose content
        ends there contributes two lines, and the third reads as missing.

        That is the right way to be wrong. The alternative - trusting the span and
        emitting a blank line the content does not contain - invents a line of source.
        """
        segments, indexed, missing = rebuild([Chunk(1, 3, "a\n\n")])
        assert shape(segments) == [("code", 1, 2), ("gap", 3, 3)]
        assert (indexed, missing) == (2, 1)


class TestWhatTheRealDataLooksLike:
    def test_the_livenessLoop_shape(self):
        """
        Nine chunks, heavily overlapping, one hole at line 13, and a parser count one
        past the last chunk. Reduced from the real spans.
        """
        segments, indexed, missing = rebuild(
            [
                Chunk(1, 9, "\n".join(f"L{i}" for i in range(1, 10))),
                Chunk(10, 12, "L10\nL11\nL12"),
                Chunk(14, 20, "\n".join(f"L{i}" for i in range(14, 21))),
                Chunk(16, 18, "L16\nL17\nL18"),
            ],
            loc=21,
        )
        assert shape(segments) == [
            ("code", 1, 12), ("gap", 13, 13), ("code", 14, 20), ("gap", 21, 21),
        ]
        assert (indexed, missing) == (19, 2)
        # Nothing doubled: nineteen lines out, nineteen distinct.
        body = text_of(segments).split("\n")
        assert len(body) == len(set(body)) == 19
