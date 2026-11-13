"""
How often each file changed, read from git while the checkout exists.

The checkout is discarded when the analysis job ends (`ingestion/scratch.py`), so this
is read during analysis and kept on the reading (`knowledge_bases.churn_json`). Two
counts per file: commits in the last `RECENT_DAYS`, and commits in the history read
(at most `MAX_COMMITS`, merges left out — a merge repeats what its branch already
counted).

A clone from a host is shallow (one commit), which has no history to count. It is
deepened for the recent window first — best effort, bounded by a timeout, and fetching
commits and trees but no file contents. If that fails the counts are what the clone
has, and `shallow` says so, so nothing presents one commit as a quiet codebase.

Language-neutral: it reads paths, never contents.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from codelith.core.logging import get_logger

logger = get_logger(__name__)

RECENT_DAYS = 90
MAX_COMMITS = 2000
_FETCH_TIMEOUT = 60.0
_LOG_TIMEOUT = 60.0


@dataclass(slots=True)
class Churn:
    #: Commits that touched each file in the last `days` days.
    recent: dict[str, int] = field(default_factory=dict)
    #: Commits that touched each file in the history read.
    total: dict[str, int] = field(default_factory=dict)
    days: int = RECENT_DAYS
    #: Commits read, and how many of them fall in the recent window.
    commits: int = 0
    recent_commits: int = 0
    #: The oldest commit read, as an ISO date: how far back "total" goes.
    since: str | None = None
    #: The history could not be deepened past a shallow clone.
    shallow: bool = False

    def to_json(self) -> dict:
        return {
            "recent": self.recent,
            "total": self.total,
            "days": self.days,
            "commits": self.commits,
            "recent_commits": self.recent_commits,
            "since": self.since,
            "shallow": self.shallow,
        }

    @classmethod
    def from_json(cls, data: dict | None) -> Churn | None:
        if not data or "total" not in data:
            return None
        return cls(
            recent={str(k): int(v) for k, v in (data.get("recent") or {}).items()},
            total={str(k): int(v) for k, v in (data.get("total") or {}).items()},
            days=int(data.get("days") or RECENT_DAYS),
            commits=int(data.get("commits") or 0),
            recent_commits=int(data.get("recent_commits") or 0),
            since=data.get("since"),
            shallow=bool(data.get("shallow")),
        )


def _git(root: Path, *args: str, timeout: float) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "-c", "core.quotepath=off", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout


def _is_shallow(root: Path) -> bool:
    return (_git(root, "rev-parse", "--is-shallow-repository", timeout=10) or "").strip() == "true"


def _deepen(root: Path, days: int) -> bool:
    """Fetch the recent window's commits into a shallow clone: commits and trees, no
    file contents (a host that cannot filter sends them anyway, which is only slower)."""
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
    started = time.monotonic()
    done = (
        _git(
            root,
            "fetch",
            "--quiet",
            "--no-tags",
            "--filter=blob:none",
            f"--shallow-since={since}",
            timeout=_FETCH_TIMEOUT,
        )
        is not None
    )
    logger.info("churn_deepen", ok=done, seconds=round(time.monotonic() - started, 1))
    return done


def parse_log(text: str, now: float, days: int = RECENT_DAYS) -> Churn:
    """`git log --format=%x00%ct --name-only` output, counted. Kept apart from the git
    call so it can be tested on a string."""
    churn = Churn(days=days)
    cutoff = now - days * 86400
    oldest: float | None = None
    for chunk in text.split("\x00"):
        lines = [x.strip() for x in chunk.strip().splitlines() if x.strip()]
        if not lines or not lines[0].isdigit():
            continue
        when = float(lines[0])
        churn.commits += 1
        oldest = when if oldest is None else min(oldest, when)
        recent = when >= cutoff
        if recent:
            churn.recent_commits += 1
        for path in set(lines[1:]):
            churn.total[path] = churn.total.get(path, 0) + 1
            if recent:
                churn.recent[path] = churn.recent.get(path, 0) + 1
    if oldest is not None:
        churn.since = datetime.fromtimestamp(oldest, UTC).date().isoformat()
    return churn


def read(
    root: str | Path, paths: set[str] | None = None, *, deepen: bool = True, rev: str | None = None
) -> Churn | None:
    """
    The change counts for the repository at `root`, kept to `paths` when given (the
    files the reading has). `None` when `root` is not inside a git repository — an
    upload, a folder that was never committed — which is not an error.

    Paths are relative to `root` even when it is a folder inside a larger repository,
    so they match the reading's own. `rev` counts the history up to that commit rather
    than up to `HEAD` — for a reading taken earlier than the folder's latest commit.
    """
    root = Path(root)
    if _git(root, "rev-parse", "--is-inside-work-tree", timeout=10) is None:
        return None
    shallow = _is_shallow(root)
    if shallow and deepen and _deepen(root, RECENT_DAYS):
        # Still shallow past the window, but the window is complete; `since` says how
        # far back the totals go.
        shallow = False
    out = _git(
        root,
        "log",
        "--no-merges",
        "--relative",
        f"-n{MAX_COMMITS}",
        "--format=%x00%ct",
        "--name-only",
        *([rev] if rev else []),
        "--",
        ".",
        timeout=_LOG_TIMEOUT,
    )
    if out is None:
        return None
    # "Recent" is counted back from the commit read: from now for the latest, from the
    # reading's own commit for an older one.
    stamps = [int(c.split()[0]) for c in out.split("\x00") if c.strip() and c.split()[0].isdigit()]
    churn = parse_log(out, max(stamps) if rev and stamps else time.time())
    # One commit is all a shallow clone has: say so rather than show a quiet codebase.
    churn.shallow = shallow or (churn.commits <= 1 and _is_shallow(root))
    if paths is not None:
        churn.recent = {p: n for p, n in churn.recent.items() if p in paths}
        churn.total = {p: n for p, n in churn.total.items() if p in paths}
    return churn


__all__ = ["MAX_COMMITS", "RECENT_DAYS", "Churn", "parse_log", "read"]
