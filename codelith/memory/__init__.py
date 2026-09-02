"""
Memory: what the analysis remembers, and where it keeps it.

The code graph has two backings — Neo4j when there is one, ordinary SQL tables when
there is not. `get_graph_store()` picks, and callers use it as a context manager
either way.
"""

from __future__ import annotations

from typing import Any

from codelith.config import get_settings

__all__ = ["get_graph_store"]


def get_graph_store(session: Any = None):
    """
    The code graph this installation queries.

    Imported inside the function so solo mode never imports the Neo4j driver — and so
    `memory/graph_store.py` stays the only module that names it, which
    `test_storage_seams.py` enforces.
    """
    if get_settings().CODELITH_PROFILE == "solo":
        from codelith.memory.sql_graph_store import SqlGraphStore

        return SqlGraphStore(session)

    from codelith.memory.graph_store import GraphStore

    return GraphStore()
