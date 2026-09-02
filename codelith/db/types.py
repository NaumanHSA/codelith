"""
The two column types that are not plain SQL.

Both existed to paper over a difference between two databases. There is one database
now, so both are simply what they always were underneath.
"""

from __future__ import annotations

from array import array

from sqlalchemy import LargeBinary, types


class PackedVector(types.TypeDecorator):
    """
    An embedding, stored as packed float32.

    3KB for 768 dimensions, against roughly 15KB as JSON text — and the whole column
    is read into a matrix on every search, so the difference is felt. float32 is also
    the precision the ranking does its arithmetic in, so nothing is lost by storing
    that rather than Python's float64.

    Reads back as a plain `list[float]`, so no caller has to know it is bytes.
    """

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: list[float] | None, dialect) -> bytes | None:
        if value is None:
            return None
        return array("f", value).tobytes()

    def process_result_value(self, value: bytes | None, dialect) -> list[float] | None:
        if value is None:
            return None
        buf = array("f")
        buf.frombytes(value)
        return list(buf)


def embedding_column(dimensions: int | None = None):
    """
    The embedding column.

    `dimensions` is accepted and ignored. It mattered when this was `vector(n)` in
    PostgreSQL, where the width is part of the type and changing it meant a migration
    that truncated the table. A blob has no declared width, so changing the embedding
    model now costs a re-ingest and no schema change at all — which is the good half
    of a trade that also gave up an index.
    """
    return PackedVector()


def json_column():
    """A JSON column. It was `JSONB` on PostgreSQL and generic everywhere else."""
    return types.JSON()
