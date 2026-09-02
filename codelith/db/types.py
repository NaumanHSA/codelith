"""
Column types that mean the same thing on more than one database.

The knowledge base is the same knowledge base whether it lives in Postgres on a
server or in a file on somebody's laptop. Only two column types differ, and both are
handled here so that no model or migration has to know which database it is talking
to.
"""

from __future__ import annotations

from array import array

from sqlalchemy import LargeBinary, types
from sqlalchemy.dialects import postgresql


class PackedVector(types.TypeDecorator):
    """
    An embedding on a database with no vector type.

    Stored as packed float32 rather than JSON: 768 dimensions is 3KB packed against
    roughly 15KB as text, and the whole column is read into a matrix on every search.
    float32 is also what the ranking does its arithmetic in, so nothing is lost by
    storing that precision rather than Python's float64.

    Reading gives back a plain `list[float]`, so callers cannot tell which database
    they are on — which is the point.
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


def embedding_column(dimensions: int):
    """
    `vector(n)` on Postgres, packed float32 everywhere else.

    Postgres gets the real type because it can index and rank with it. Everything
    else gets bytes, and the ranking happens in the process — measured faster than
    the round trip for any repository that fits on one machine, and exact where the
    HNSW index is approximate.
    """
    from pgvector.sqlalchemy import Vector

    return Vector(dimensions).with_variant(PackedVector(), "sqlite")


def json_column():
    """
    `JSONB` on Postgres, generic JSON everywhere else.

    Existing migrations name `postgresql.JSONB` directly; this exists for new columns
    and for the day those are made portable.
    """
    return types.JSON().with_variant(postgresql.JSONB(), "postgresql")
