"""
A change, as a review reads it: which files moved, which lines, and what they say now.

Collected from git, on whichever machine has the working copy — the CLI's, the server's
for a folder it reads, the MCP server's for the editor it runs beside — and handed to
`knowledge/review.py` as plain data. Plain data on purpose: the CLI collects a change
locally and sends it to a server that has no checkout of the repository at all, which
is the normal case for a codebase read from GitHub.

Line ranges are kept for both sides. The old side is what the knowledge base's symbols
are numbered against (it describes the code before the change); the new side is what
a person reading the change sees.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

#: A change bigger than this is not reviewed file by file; the rest is listed as skipped.
MAX_FILES = 300
#: Content kept per file. A generated file of megabytes says nothing a review can use.
MAX_BYTES = 400_000

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(slots=True)
class ChangedFile:
    path: str
    #: `added` | `modified` | `deleted` | `renamed`
    status: str
    old_path: str | None = None
    #: Inclusive line ranges, old and new numbering. A pure insertion has no old range.
    old_ranges: list[tuple[int, int]] = field(default_factory=list)
    new_ranges: list[tuple[int, int]] = field(default_factory=list)
    #: The file as it is now; None when deleted, binary, or too large.
    content: str | None = None

    @property
    def before(self) -> str:
        """The path the knowledge base knows it by."""
        return self.old_path or self.path


@dataclass(slots=True)
class ChangeSet:
    #: What it was compared against: a commit, a branch, `HEAD`.
    base: str
    #: The other side; None for the working copy (uncommitted changes included).
    head: str | None
    files: list[ChangedFile] = field(default_factory=list)
    #: Files left out because the change was larger than `MAX_FILES`.
    skipped: int = 0
    #: Their paths. Not reviewed, but known to have changed: a check that asks "is this
    #: importer part of the change?" must not answer no for a file it merely did not read.
    left_out: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ChangeSet:
        files = [
            ChangedFile(
                path=f["path"],
                status=f.get("status", "modified"),
                old_path=f.get("old_path"),
                old_ranges=[tuple(r) for r in f.get("old_ranges") or []],
                new_ranges=[tuple(r) for r in f.get("new_ranges") or []],
                content=f.get("content"),
            )
            for f in (data.get("files") or [])[:MAX_FILES]
        ]
        overflow = [f["path"] for f in (data.get("files") or [])[MAX_FILES:]]
        return cls(
            base=str(data.get("base") or "HEAD"),
            head=data.get("head"),
            files=files,
            skipped=int(data.get("skipped") or 0) + len(overflow),
            left_out=[*(data.get("left_out") or []), *overflow][:20_000],
        )


class ChangeError(Exception):
    """A sentence for the person asking: not a repository, an unknown commit."""


def _git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except FileNotFoundError as exc:
        raise ChangeError("git is not available on this machine.") from exc
    except subprocess.CalledProcessError as exc:
        raise ChangeError((exc.stderr or exc.stdout or "git failed").strip().splitlines()[-1]) from exc
    return out.stdout


def has_commit(root: Path, ref: str) -> bool:
    try:
        _git(root, "cat-file", "-e", f"{ref}^{{commit}}")
        return True
    except ChangeError:
        return False


def collect(path: Path, base: str, head: str | None = None) -> ChangeSet:
    """
    The change between `base` and `head` — or, with no `head`, between `base` and the
    working copy, uncommitted and untracked files included, which is what "review what
    I am about to commit" means.

    Paths come back relative to `path`, so a codebase read from a folder inside a
    larger repository sees its own paths; files outside it are not part of its change.
    """
    path = Path(path).expanduser().resolve()
    try:
        root = Path(_git(path, "rev-parse", "--show-toplevel").strip()).resolve()
    except ChangeError as exc:
        raise ChangeError(f"{path} is not inside a git repository.") from exc
    if not has_commit(root, base):
        raise ChangeError(f"{base} is not a commit in this repository. Fetch it, or pass another base.")
    if head and not has_commit(root, head):
        raise ChangeError(f"{head} is not a commit in this repository.")

    prefix = path.relative_to(root).as_posix() if path != root else ""
    span = [base, head] if head else [base]

    statuses: dict[str, tuple[str, str | None]] = {}
    for line in _git(root, "diff", "--name-status", "-M", *span).splitlines():
        parts = line.split("\t")
        code = parts[0][:1]
        if code == "R" and len(parts) >= 3:
            statuses[parts[2]] = ("renamed", parts[1])
        elif code == "A":
            statuses[parts[1]] = ("added", None)
        elif code == "D":
            statuses[parts[1]] = ("deleted", None)
        elif len(parts) >= 2:
            statuses[parts[-1]] = ("modified", None)
    if not head:
        for line in _git(root, "ls-files", "--others", "--exclude-standard").splitlines():
            if line.strip():
                statuses.setdefault(line.strip(), ("added", None))

    ranges = _ranges(_git(root, "diff", "-M", "-U0", "--no-color", *span))

    files: list[ChangedFile] = []
    left_out: list[str] = []
    for repo_path, (status, old) in sorted(statuses.items()):
        rel = _within(repo_path, prefix)
        if rel is None:
            continue
        if len(files) >= MAX_FILES:
            left_out.append(rel)
            continue
        old_rel = _within(old, prefix) if old else None
        old_r, new_r = ranges.get(repo_path, ([], []))
        changed = ChangedFile(path=rel, status=status, old_path=old_rel, old_ranges=old_r, new_ranges=new_r)
        if status != "deleted":
            changed.content = _content(root, repo_path, head)
            if status == "added" and not new_r and changed.content is not None:
                # An untracked file is all new; git gave no hunks for it.
                changed.new_ranges = [(1, max(1, changed.content.count("\n") + 1))]
        files.append(changed)

    return ChangeSet(base=base, head=head, files=files, skipped=len(left_out), left_out=left_out)


def _within(repo_path: str, prefix: str) -> str | None:
    if not prefix:
        return repo_path
    p = PurePosixPath(repo_path)
    try:
        return p.relative_to(prefix).as_posix()
    except ValueError:
        return None


def _content(root: Path, repo_path: str, head: str | None) -> str | None:
    try:
        if head:
            text = _git(root, "show", f"{head}:{repo_path}")
        else:
            file = root / repo_path
            if not file.is_file() or file.stat().st_size > MAX_BYTES:
                return None
            raw = file.read_bytes()
            if b"\0" in raw[:8000]:
                return None  # binary
            text = raw.decode("utf-8", errors="replace")
    except (ChangeError, OSError):
        return None
    return text if len(text) <= MAX_BYTES else None


def _ranges(diff: str) -> dict[str, tuple[list[tuple[int, int]], list[tuple[int, int]]]]:
    """Changed line ranges per file, from a `-U0` diff, keyed by the new path."""
    out: dict[str, tuple[list[tuple[int, int]], list[tuple[int, int]]]] = {}
    current: str | None = None
    old_path: str | None = None
    for line in diff.splitlines():
        if line.startswith("--- "):
            old_path = None if line.endswith("/dev/null") else line[4:].removeprefix("a/")
        elif line.startswith("+++ "):
            current = old_path if line.endswith("/dev/null") else line[4:].removeprefix("b/")
            if current is not None:
                out.setdefault(current, ([], []))
        elif current and (m := _HUNK.match(line)):
            a, b, c, d = m.groups()
            old_len = 1 if b is None else int(b)
            new_len = 1 if d is None else int(d)
            if old_len:
                out[current][0].append((int(a), int(a) + old_len - 1))
            if new_len:
                out[current][1].append((int(c), int(c) + new_len - 1))
    return out


def overlaps(ranges: list[tuple[int, int]], start: int | None, end: int | None) -> bool:
    """Whether a symbol spanning `start`–`end` was touched by any of the ranges."""
    if start is None:
        return False
    stop = end if end is not None else start
    return any(a <= stop and start <= b for a, b in ranges)


__all__ = ["ChangeError", "ChangeSet", "ChangedFile", "MAX_FILES", "collect", "has_commit", "overlaps"]
