"""
Vectors from two different embedding models must not meet.

Every embedding model produces vectors of its own width, and cosine similarity is only
defined between vectors of the same one. Change the embedding model and the knowledge
bases already built are not *stale* — they are unreadable by the new model, and there
is no partial answer to fall back to.

**This used to be a setting.** `VECTOR_DIMENSIONS` sat in `.env` and the operator was
expected to keep it in step with whichever model they had loaded. It also, by then, did
nothing: the column is a blob with no declared width, so nothing checked it and nothing
could. What actually happened on a mismatch was a `ValueError: setting an array element
with a sequence` out of numpy, at search time, from a stack nobody would connect to a
model they changed last week.

So the width is **measured, never configured** — recorded on the knowledge base when it
is built, and compared against the model in use when it is read. The comparison is on
the model *name* as well as the width, because two models can share a width and still
disagree completely about what a vector means: same shape, meaningless answers, and
nothing anywhere would say so.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

#: Where this lives inside `KnowledgeBase.stats_json`. A key rather than a column: it
#: is a property of the reading, which is what `stats_json` already holds, and adding
#: it needs no migration for the installs that already exist.
STATS_KEY = "embedding"


@dataclass(frozen=True, slots=True)
class Mismatch:
    """A knowledge base that the configured embedding model cannot read."""

    kb_model: str
    kb_dimensions: int | None
    current_model: str
    current_dimensions: int | None

    def message(self) -> str:
        """What to tell somebody, including what to do about it."""
        if self.kb_dimensions and self.current_dimensions and (
            self.kb_dimensions != self.current_dimensions
        ):
            detail = (
                f"{self.kb_dimensions}-dimension vectors, and "
                f"'{self.current_model}' produces {self.current_dimensions}"
            )
        else:
            detail = (
                f"vectors from '{self.kb_model}', and a vector only means anything to "
                "the model that produced it"
            )
        return (
            f"This codebase was indexed with '{self.kb_model}' — {detail}. "
            f"Search and every answer built on it need re-analysing with "
            f"'{self.current_model}', or the embedding model switching back."
        )


def record(model: str, dimensions: int | None) -> dict:
    """The block to store on `KnowledgeBase.stats_json` when a reading is built."""
    return {"model": model, "dimensions": dimensions}


def stored(stats: dict | None) -> tuple[str | None, int | None]:
    """
    What a knowledge base was indexed with, or `(None, None)`.

    `None` for anything built before this was recorded. Those are not treated as a
    mismatch: refusing to read every knowledge base that predates the check would be
    a worse failure than the one being prevented, and the model has probably not
    changed. It is an absence of evidence, and it is reported as such.
    """
    block = (stats or {}).get(STATS_KEY) or {}
    return block.get("model"), block.get("dimensions")


def check(stats: dict | None, *, current_model: str, current_dimensions: int | None = None):
    """
    Whether the configured embedding model can read this knowledge base.

    Returns a `Mismatch` or `None`. Unknown provenance returns `None` — see `stored`.
    """
    kb_model, kb_dimensions = stored(stats)
    if not kb_model:
        return None
    if kb_model == current_model:
        return None
    return Mismatch(
        kb_model=kb_model,
        kb_dimensions=kb_dimensions,
        current_model=current_model,
        current_dimensions=current_dimensions,
    )


def usable(rows: list, width: int) -> list:
    """
    The rows whose vectors the query can actually be compared against.

    A filter rather than a raise, and the two are not alternatives — the check above
    is what produces the message somebody can act on, and this is what stops the
    process falling over while they read it. numpy will not build a matrix from ragged
    rows, so without this a single stray vector takes out the whole search.
    """
    keep = [r for r in rows if r.embedding is not None and len(r.embedding) == width]
    if len(keep) != len(rows):
        logger.warning(
            "embedding_width_mismatch",
            expected=width,
            skipped=len(rows) - len(keep),
            hint="this knowledge base holds vectors from more than one embedding model",
        )
    return keep


__all__ = ["Mismatch", "STATS_KEY", "check", "record", "stored", "usable"]
