"""
Ranking without a database that can rank.

Postgres orders by `<=>` inside the query. SQLite has no such operator, so solo mode
brings the filtered rows back and ranks them here. The two paths must choose the same
chunks in the same order, or "it behaves the same locally" is a claim nobody checked.

The local path is in fact the more accurate of the two: HNSW is an approximate index
and this is exact. That is worth knowing when the two ever disagree — the server is
the one that is allowed to be wrong.
"""

from __future__ import annotations

import math

import pytest

from codelith.memory.vector_store import VectorStore, _rank_by_cosine


class _Chunk:
    """Enough of a CodeChunk to be ranked."""

    def __init__(self, ident: str, embedding: list[float]) -> None:
        self.id = ident
        self.embedding = embedding

    def __repr__(self) -> str:  # pragma: no cover - test output only
        return f"<{self.id}>"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class TestRanking:
    def test_nearest_first(self) -> None:
        query = [1.0, 0.0]
        rows = [
            _Chunk("opposite", [-1.0, 0.0]),
            _Chunk("exact", [1.0, 0.0]),
            _Chunk("orthogonal", [0.0, 1.0]),
        ]
        assert [c.id for c in _rank_by_cosine(rows, query, 3)] == [
            "exact",
            "orthogonal",
            "opposite",
        ]

    def test_magnitude_does_not_matter_only_direction(self) -> None:
        """Cosine, not dot product — a long vector pointing elsewhere must not win."""
        query = [1.0, 0.0]
        rows = [
            _Chunk("long-but-wrong", [1.0, 40.0]),
            _Chunk("short-and-right", [0.2, 0.0]),
        ]
        assert _rank_by_cosine(rows, query, 1)[0].id == "short-and-right"

    def test_limit_is_honoured_and_never_over_runs(self) -> None:
        rows = [_Chunk(str(i), [float(i), 1.0]) for i in range(5)]
        assert len(_rank_by_cosine(rows, [1.0, 1.0], 3)) == 3
        # Asking for more than exists returns everything, not an error.
        assert len(_rank_by_cosine(rows, [1.0, 1.0], 99)) == 5

    def test_it_agrees_with_a_plain_python_cosine(self) -> None:
        """
        The property that matters: same chunks, same order as the definition.

        Numpy, `argpartition` and the norm handling are all opportunities to be
        subtly wrong in a way that still returns plausible results.
        """
        import random

        rnd = random.Random(7)
        rows = [
            _Chunk(str(i), [rnd.uniform(-1, 1) for _ in range(16)]) for i in range(200)
        ]
        query = [rnd.uniform(-1, 1) for _ in range(16)]

        expected = [
            c.id
            for c in sorted(rows, key=lambda c: -_cosine(c.embedding, query))[:10]
        ]
        assert [c.id for c in _rank_by_cosine(rows, query, 10)] == expected

    def test_no_rows_is_not_an_error(self) -> None:
        assert _rank_by_cosine([], [1.0, 0.0], 5) == []

    def test_a_zero_query_returns_nothing_rather_than_an_arbitrary_slice(self) -> None:
        """A zero vector has no direction; every result would be equally meaningless."""
        rows = [_Chunk("a", [1.0, 0.0]), _Chunk("b", [0.0, 1.0])]
        assert _rank_by_cosine(rows, [0.0, 0.0], 2) == []

    def test_one_bad_embedding_does_not_take_out_the_search(self) -> None:
        """A zero-vector row would divide by zero. It should rank last, not raise."""
        rows = [_Chunk("zero", [0.0, 0.0]), _Chunk("good", [1.0, 0.0])]
        assert _rank_by_cosine(rows, [1.0, 0.0], 2)[0].id == "good"


class TestWhoDoesTheRanking:
    """
    Decided by the connection, not by configuration.

    A SQLite database cannot order by cosine distance whatever a setting claims, and
    a profile flag that disagreed with the bind would fail at query time with an
    error about a missing operator.
    """

    @pytest.mark.parametrize(
        "dialect,in_database",
        [("postgresql", True), ("sqlite", False), ("", False)],
    )
    def test_dialect_decides(self, dialect: str, in_database: bool) -> None:
        class _Dialect:
            name = dialect

        class _Bind:
            dialect = _Dialect()

        class _Session:
            def get_bind(self):
                return _Bind()

        store = VectorStore.__new__(VectorStore)
        store.session = _Session()  # type: ignore[assignment]
        assert store._ranks_in_database() is in_database
