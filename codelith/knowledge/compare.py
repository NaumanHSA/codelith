"""
Two readings of the same codebase, compared line by line.

Every reading keeps its files (`reading_files`), each distinct content stored once,
so the comparison starts from two path-to-hash lists: a path whose hash is the same in
both did not change, and nothing about it is read. Only the files that differ are
decompressed and diffed.

What this adds to `git diff` is the other half of the page: each changed file comes
with what the later reading knows about it — its part, how many files depend on it,
whether a test reaches it, which written pages cite it. A one-line change to a file
forty others import is not the same change as one to a leaf, and the diff alone never
says which it is.

Renames are found as git finds them: identical content under a new path, or content
at least 60% alike in a file of the same kind.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from codelith.db.repositories.knowledge.source_repo import SourceRepository, StoredFile
from codelith.knowledge.risk import RiskService
from codelith.models.knowledge import KnowledgeBase

#: Content at least this alike, in two files with the same extension, is a rename.
RENAME_SIMILARITY = 0.6
#: A file longer than this is compared, but not counted line by line or shown whole.
LARGE_LINES = 20_000
#: At most this many removed x added pairs are scored for renames.
_RENAME_PAIRS = 2_500
#: Words, runs of space and single punctuation: what a changed line is split into
#: to mark the words that changed within it.
_TOKENS = re.compile(r"\w+|\s+|[^\w\s]")


@dataclass(slots=True)
class FileChange:
    path: str
    #: `added`, `removed`, `modified` or `renamed`.
    status: str
    old_path: str | None = None
    added: int = 0
    removed: int = 0
    language: str | None = None
    kind: str | None = None
    #: Too long to count or show whole.
    large: bool = False
    similarity: float | None = None
    # What the reading knows about it (the later one, or the earlier for a removed file).
    part: str | None = None
    reach: int = 0
    direct: int = 0
    tests: int = 0
    pages: int = 0


@dataclass(slots=True)
class Comparison:
    available: bool
    reason: str = ""
    before: int | None = None
    after: int | None = None
    #: Which of the two readings kept no files, when that is why it is unavailable.
    missing: list[int] = field(default_factory=list)
    files: list[FileChange] = field(default_factory=list)

    @property
    def added(self) -> int:
        return sum(f.added for f in self.files)

    @property
    def removed(self) -> int:
        return sum(f.removed for f in self.files)


@dataclass(slots=True)
class Row:
    #: `context`, `add` or `del`.
    kind: str
    old: int | None
    new: int | None
    text: str
    #: Character ranges within `text` that changed, for a line paired with its
    #: counterpart on the other side.
    marks: list[tuple[int, int]] = field(default_factory=list)


@dataclass(slots=True)
class FileDiff:
    path: str
    old_path: str | None
    status: str
    language: str | None
    #: Every line when `whole`; otherwise hunks with three lines of context.
    rows: list[Row] = field(default_factory=list)
    whole: bool = True
    old_lines: int = 0
    new_lines: int = 0
    masked: bool = False


def _lines(text: str | None) -> list[str]:
    return (text or "").splitlines()


def _count(a: list[str], b: list[str]) -> tuple[int, int]:
    added = removed = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            removed += i2 - i1
        if op in ("replace", "insert"):
            added += j2 - j1
    return added, removed


def _marks(old: str, new: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """The character ranges that differ between a removed line and the one replacing it."""
    a, b = _TOKENS.findall(old), _TOKENS.findall(new)
    pos_a = [0]
    for t in a:
        pos_a.append(pos_a[-1] + len(t))
    pos_b = [0]
    for t in b:
        pos_b.append(pos_b[-1] + len(t))
    out_a: list[tuple[int, int]] = []
    out_b: list[tuple[int, int]] = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    # A line rewritten end to end is not worth marking word by word: mark nothing.
    # Judged on the words alone, or the spaces between them make any two lines alike.
    words = difflib.SequenceMatcher(
        None, [t for t in a if not t.isspace()], [t for t in b if not t.isspace()], autojunk=False
    )
    if words.ratio() < 0.3:
        return [], []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        if i2 > i1:
            out_a.append((pos_a[i1], pos_a[i2]))
        if j2 > j1:
            out_b.append((pos_b[j1], pos_b[j2]))
    return out_a, out_b


def diff_rows(a: list[str], b: list[str], context: int | None = None) -> list[Row]:
    """
    The rows of a diff. `context=None` gives every line; a number gives hunks with
    that many unchanged lines around each change, and nothing between them.
    """
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    groups = [matcher.get_opcodes()] if context is None else list(matcher.get_grouped_opcodes(context))
    rows: list[Row] = []
    for group in groups:
        for op, i1, i2, j1, j2 in group:
            if op == "equal":
                rows += [Row("context", i1 + k + 1, j1 + k + 1, a[i1 + k]) for k in range(i2 - i1)]
                continue
            dels = [Row("del", i1 + k + 1, None, a[i1 + k]) for k in range(i2 - i1)]
            adds = [Row("add", None, j1 + k + 1, b[j1 + k]) for k in range(j2 - j1)]
            # Lines replaced one for one are paired, and the words that changed marked.
            for d, n in zip(dels, adds, strict=False):
                d.marks, n.marks = _marks(d.text, n.text)
            rows += dels + adds
    return rows


class CompareService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.sources = SourceRepository(db)

    async def files(self, before: KnowledgeBase, after: KnowledgeBase) -> Comparison:
        out = Comparison(available=False, before=before.id, after=after.id)
        missing = [kb.id for kb in (before, after) if not await self.sources.has_snapshot(kb.id)]
        if missing:
            out.missing = missing
            out.reason = (
                "One of these readings was taken before Codelith kept each reading's files. "
                "Fetch its files from git to compare them line by line."
            )
            return out
        out.available = True

        old = {f.path: f for f in await self.sources.files(before.id)}
        new = {f.path: f for f in await self.sources.files(after.id)}
        removed = sorted(set(old) - set(new))
        added = sorted(set(new) - set(old))
        changed = sorted(p for p in set(old) & set(new) if old[p].hash != new[p].hash)

        renamed: dict[str, tuple[str, float]] = {}  # new path -> (old path, similarity)
        by_hash: dict[str, list[str]] = {}
        for path in removed:
            by_hash.setdefault(old[path].hash, []).append(path)
        for path in added:
            if candidates := by_hash.get(new[path].hash):
                renamed[path] = (candidates.pop(0), 1.0)
        await self._similar(old, new, [p for p in removed if p not in {o for o, _ in renamed.values()}],
                            [p for p in added if p not in renamed], renamed)
        gone = {o for o, _ in renamed.values()}

        texts: dict[str, str] = {}

        async def text(f: StoredFile) -> str:
            if f.hash not in texts:
                texts[f.hash] = await self.sources.text(f.hash) or ""
            return texts[f.hash]

        files: list[FileChange] = []
        for path in changed:
            f = new[path]
            change = FileChange(path, "modified", language=f.language, kind=f.kind)
            if max(old[path].lines, f.lines) > LARGE_LINES:
                change.large = True
            else:
                change.added, change.removed = _count(_lines(await text(old[path])), _lines(await text(f)))
            files.append(change)
        for path in added:
            f = new[path]
            if path in renamed:
                source, similarity = renamed[path]
                change = FileChange(path, "renamed", old_path=source, language=f.language, kind=f.kind, similarity=similarity)
                if similarity < 1.0:
                    change.added, change.removed = _count(_lines(await text(old[source])), _lines(await text(f)))
            else:
                change = FileChange(path, "added", language=f.language, kind=f.kind, added=f.lines, large=f.lines > LARGE_LINES)
            files.append(change)
        for path in removed:
            if path in gone:
                continue
            f = old[path]
            files.append(FileChange(path, "removed", language=f.language, kind=f.kind, removed=f.lines, large=f.lines > LARGE_LINES))

        await self._blast(before, after, files)
        files.sort(key=lambda c: c.path)
        out.files = files
        return out

    async def _similar(
        self,
        old: dict[str, StoredFile],
        new: dict[str, StoredFile],
        removed: list[str],
        added: list[str],
        renamed: dict[str, tuple[str, float]],
    ) -> None:
        """Pair a removed and an added file of the same extension that are mostly alike."""
        pairs = [
            (a, r)
            for a in added
            for r in removed
            if PurePosixPath(a).suffix == PurePosixPath(r).suffix
        ][:_RENAME_PAIRS]
        if not pairs:
            return
        cache: dict[str, list[str]] = {}

        async def lines(f: StoredFile) -> list[str]:
            if f.hash not in cache:
                cache[f.hash] = _lines(await self.sources.text(f.hash))
            return cache[f.hash]

        scored: list[tuple[float, str, str]] = []
        for a, r in pairs:
            na, nr = new[a].lines, old[r].lines
            if not na or not nr or min(na, nr) / max(na, nr) < RENAME_SIMILARITY:
                continue
            matcher = difflib.SequenceMatcher(None, await lines(old[r]), await lines(new[a]), autojunk=False)
            if matcher.real_quick_ratio() < RENAME_SIMILARITY or matcher.quick_ratio() < RENAME_SIMILARITY:
                continue
            ratio = matcher.ratio()
            if ratio >= RENAME_SIMILARITY:
                scored.append((ratio, a, r))
        taken: set[str] = set()
        for ratio, a, r in sorted(scored, reverse=True):
            if a in renamed or r in taken:
                continue
            renamed[a] = (r, round(ratio, 2))
            taken.add(r)

    async def _blast(self, before: KnowledgeBase, after: KnowledgeBase, files: list[FileChange]) -> None:
        """What each reading knows about the files that changed: part, reach, tests, pages."""
        if not files:
            return
        later = {r.path: r for r in (await RiskService(self.db, after).rank(limit=1_000_000))[0]}
        earlier: dict = {}
        if any(f.status == "removed" for f in files):
            earlier = {r.path: r for r in (await RiskService(self.db, before).rank(limit=1_000_000))[0]}
        for change in files:
            risk = (earlier if change.status == "removed" else later).get(change.path)
            if risk is None:
                continue
            change.part = risk.component or None
            change.reach, change.direct, change.tests, change.pages = risk.reach, risk.direct, risk.tests, risk.pages

    async def file(
        self, before: KnowledgeBase, after: KnowledgeBase, path: str, old_path: str | None = None
    ) -> FileDiff | None:
        """One file's diff. `old_path` for a renamed file. `None` when neither reading has it."""
        was = await self.sources.entry(before.id, old_path or path)
        now = await self.sources.entry(after.id, path)
        if was is None and now is None:
            return None
        a = _lines(await self.sources.text(was.hash)) if was else []
        b = _lines(await self.sources.text(now.hash)) if now else []
        status = "added" if was is None else "removed" if now is None else "renamed" if old_path and old_path != path else "modified"
        whole = max(len(a), len(b)) <= LARGE_LINES
        return FileDiff(
            path=path,
            old_path=old_path if status == "renamed" else None,
            status=status,
            language=(now or was).language,
            rows=diff_rows(a, b, None if whole else 3),
            whole=whole,
            old_lines=len(a),
            new_lines=len(b),
            masked=bool((now and now.masked) or (was and was.masked)),
        )


__all__ = ["CompareService", "Comparison", "FileChange", "FileDiff", "Row", "diff_rows"]
