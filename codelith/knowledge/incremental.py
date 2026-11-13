"""
Reading a codebase again without starting from zero.

A reading used to begin from nothing every time: every file parsed, every chunk
embedded, every module summarised, every narrative written — minutes of a model's time
on a local machine, to record that one line changed. Most of that work depends only on
file contents, and every reading already keeps a fingerprint of each file
(`file_hashes_json`). So a new reading compares its fingerprints with the last
reading's and keeps whatever the comparison says cannot have changed:

    facts and the code graph   rebuilt — no model involved, and fast
    search vectors             a chunk with the same file and the same text keeps its
                               vector; only new or changed chunks are embedded
    module summaries           a module whose files are all unchanged keeps its summary
    architecture               kept while the codebase's structure is unchanged: the same
                               modules, none of them re-summarised, no manifest touched
    narratives                 a topic is kept when the modules and facts it was written
                               from are the same and none of those modules changed
    site plan, questions       kept while the structure is unchanged

What may be kept is decided here, once, from fingerprints, and handed to every stage
as a plain dict in the analysis state (`reuse`). Each stage adds what it actually kept,
and the persister records the whole of it on the reading, so a run can say what it
saved instead of asking to be believed.

`force` reads everything from scratch, as before. So does a first reading, a previous
reading without fingerprints, and — for vectors only — a change of embedding model,
because a vector is only comparable with vectors from the model that made it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FileDelta:
    """How two readings' files differ, by path."""

    changed: frozenset[str]
    added: frozenset[str]
    removed: frozenset[str]
    unchanged: frozenset[str]

    @property
    def touched(self) -> frozenset[str]:
        return self.changed | self.added | self.removed


def compare_files(previous: dict[str, str], current: dict[str, str]) -> FileDelta:
    """Fingerprint by fingerprint: what changed, what is new, what went, what stayed."""
    before = set(previous)
    after = set(current)
    both = before & after
    changed = frozenset(p for p in both if previous[p] != current[p])
    return FileDelta(
        changed=changed,
        added=frozenset(after - before),
        removed=frozenset(before - after),
        unchanged=frozenset(both - changed),
    )


def plan(
    previous: Any | None,
    current_hashes: dict[str, str],
    *,
    force: bool,
    embedding_model: str | None,
) -> dict[str, Any]:
    """
    The reuse record a reading starts with.

    `previous` is the reading to take from (a `KnowledgeBase`), or None. The record is
    a plain dict because it travels through the analysis state and ends up in the
    reading's stats as JSON.
    """
    if force:
        return {"from_kb": None, "reason": "forced: read everything from scratch"}
    if previous is None:
        return {"from_kb": None, "reason": "first reading of this codebase"}
    before = previous.file_hashes_json or {}
    if not before:
        return {"from_kb": None, "reason": "the last reading kept no file fingerprints"}

    delta = compare_files(before, current_hashes)
    stats = previous.stats_json or {}
    previous_model = (stats.get("embedding") or {}).get("model")
    return {
        "from_kb": previous.id,
        "from_commit": previous.commit_sha,
        # Kept as lists: the record is JSON. Small next to the fingerprints themselves.
        "changed": sorted(delta.changed),
        "added": sorted(delta.added),
        "removed": sorted(delta.removed),
        "unchanged": len(delta.unchanged),
        "vectors": bool(previous_model) and previous_model == embedding_model,
        # A degraded architecture came from the fallback; worth asking the model again.
        "architecture_ok": "architecture map came from" not in (previous.error_message or ""),
    }


def active(reuse: dict[str, Any] | None) -> bool:
    """Whether there is a previous reading to take from at all."""
    return bool(reuse and reuse.get("from_kb"))


def touched(reuse: dict[str, Any] | None) -> set[str]:
    """Every path that changed, appeared or disappeared since the previous reading."""
    if not reuse:
        return set()
    return set(reuse.get("changed") or ()) | set(reuse.get("added") or ()) | set(reuse.get("removed") or ())


def files_unchanged(reuse: dict[str, Any] | None, paths: Iterable[str]) -> bool:
    """True when every path is the same as in the previous reading."""
    if not active(reuse):
        return False
    moved = touched(reuse)
    return not any(p in moved for p in paths)


def structure_unchanged(reuse: dict[str, Any] | None) -> bool:
    """
    Whether what the model-written overviews are written from is the same.

    Set by the module summarizer, which is the stage that sees both readings' modules:
    the same set of modules, none of them re-summarised, and no file outside every
    module (a manifest, a compose file) touched. Architecture, the site plan and the
    suggested questions are kept only while this holds.
    """
    return active(reuse) and bool(reuse.get("structure_unchanged"))


def note(reuse: dict[str, Any] | None, **counts: Any) -> dict[str, Any]:
    """The record with one stage's outcome added. Returns a new dict: the analysis state
    has no reducers, so a stage hands back the whole key it changed."""
    return {**(reuse or {}), **counts}


def summary(reuse: dict[str, Any] | None) -> dict[str, Any]:
    """What the reading stores about its reuse: the counts, not the file lists."""
    if not reuse:
        return {}
    out = {k: v for k, v in reuse.items() if k not in {"changed", "added", "removed"}}
    if active(reuse):
        out["files_changed"] = len(reuse.get("changed") or ())
        out["files_added"] = len(reuse.get("added") or ())
        out["files_removed"] = len(reuse.get("removed") or ())
    return out
