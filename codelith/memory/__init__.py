"""
Memory: what the analysis remembers, and where it keeps it.

The code graph lives in ordinary SQL tables alongside everything else. There was a
Neo4j backing and a factory to choose between them; both are gone. One implementation
is one thing to keep working.
"""

from __future__ import annotations

from typing import Any

__all__ = ["get_graph_store"]


def get_graph_store(session: Any = None):
    """The code graph. Kept as a function so callers read the same as before."""
    from codelith.memory.sql_graph_store import SqlGraphStore

    return SqlGraphStore(session)
