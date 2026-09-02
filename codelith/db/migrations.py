"""
Helpers for migrations that must run on more than one database.

Almost the whole schema is portable — `TIMESTAMP` and `JSONB` map onto their generic
equivalents, and everything else is ordinary DDL. Four things are not, and all four
are about the vector column: the extension that provides it, the type itself, the HNSW
index over it, and a `TRUNCATE`/`ALTER TYPE` pair in the migration that resized it.

Rather than fork the migration chain, those four ask `is_postgres()` first. A solo
database therefore runs the *same* migrations, gets every table, and can be upgraded
later — which a schema built from `create_all` and stamped at head could not be.

**The rule this establishes:** a new migration must run on both. If it needs something
only Postgres has, guard it here rather than assuming the dialect.
"""

from __future__ import annotations

from alembic import op


def is_postgres() -> bool:
    """Whether the migration is running against PostgreSQL."""
    return op.get_bind().dialect.name == "postgresql"
