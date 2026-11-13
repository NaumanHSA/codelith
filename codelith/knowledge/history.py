"""
A codebase's history: its commits, and its readings one after another.

**Commits.** While analysis has a checkout it reads the commits (hash, parents, author's
name, date, subject, files — never an email) and keeps them per codebase, once per
commit (`source_commits`). The commits between two readings are then exactly what git
would say: reachable from the later reading's commit and not from the earlier one's. A
codebase read before this was kept has none; `HistoryService.fetch` reads them from the
folder (a local source is only read, never changed) or from a blobless clone of ours.

**Readings.** Each reading against the one before it: files and lines changed, the parts
they belong to, and the commits between — what the History page lists. And one file's
own history: the readings where its content changed.

Language-neutral: it reads paths and hashes, never what a file says.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.knowledge.churn import _git
from codelith.knowledge.constants import KBStatus
from codelith.models.knowledge import KnowledgeBase
from codelith.models.source import ReadingFile, SourceCommit

logger = structlog.get_logger(__name__)

#: Commits read at most, newest first.
MAX_COMMITS = 1000
_LOG_TIMEOUT = 90.0
_CLONE_TIMEOUT = 300.0
_HOSTED = ("github", "gitlab", "bitbucket")
_COMPARABLE = (KBStatus.READY, KBStatus.STALE, KBStatus.DEGRADED)
_RECORD, _FIELD = "\x1e", "\x1f"


@dataclass(slots=True)
class Commit:
    sha: str
    parents: tuple[str, ...]
    author: str
    when: datetime | None
    subject: str
    files: tuple[str, ...] = ()

    @property
    def merge(self) -> bool:
        return len(self.parents) > 1


def parse_commits(text: str) -> list[Commit]:
    """`git log --format=%x1e%H%x1f%P%x1f%an%x1f%aI%x1f%s --name-only`, as commits."""
    out: list[Commit] = []
    for chunk in text.split(_RECORD):
        if not chunk.strip():
            continue
        head, _, rest = chunk.partition("\n")
        fields = head.split(_FIELD)
        if len(fields) < 5 or len(fields[0]) < 7:
            continue
        sha, parents, author, date, subject = fields[0], fields[1], fields[2], fields[3], _FIELD.join(fields[4:])
        try:
            when = datetime.fromisoformat(date.strip()) if date.strip() else None
        except ValueError:
            when = None
        files = tuple(dict.fromkeys(line.strip() for line in rest.splitlines() if line.strip()))
        out.append(Commit(sha.strip(), tuple(parents.split()), author.strip(), when, subject.strip(), files))
    return out


def read_commits(root: str | Path, rev: str | None = None, limit: int = MAX_COMMITS) -> list[Commit] | None:
    """
    The commits behind `rev` (or HEAD) that touch the folder at `root`, newest first.
    `None` when `root` is not in a git repository. Parents are rewritten to the folder's
    own history, so a codebase that is one folder of a larger repository still links up.
    """
    root = Path(root)
    if _git(root, "rev-parse", "--git-dir", timeout=10) is None:
        return None
    out = _git(
        root,
        "log",
        "--parents",
        "--relative",
        f"-n{limit}",
        f"--format={_RECORD}%H{_FIELD}%P{_FIELD}%an{_FIELD}%aI{_FIELD}%s",
        "--name-only",
        *([rev] if rev else []),
        "--",
        ".",
        timeout=_LOG_TIMEOUT,
    )
    return None if out is None else parse_commits(out)


@dataclass(slots=True)
class Between:
    commits: list[SourceCommit] = field(default_factory=list)
    #: Every commit between was kept. False when the kept history stops short.
    complete: bool = True
    #: Nothing kept for the later reading's commit at all.
    known: bool = True
    reason: str = ""


def between(kept: list[SourceCommit], before: str | None, after: str | None) -> Between:
    """The commits reachable from `after` and not from `before`, newest first."""
    index = {c.sha: c for c in kept}
    if not after or after not in index:
        return Between(known=False, complete=False, reason="No commits are kept for this reading's commit yet.")

    def walk(start: str, stop: set[str] | None = None) -> tuple[set[str], bool]:
        seen: set[str] = set()
        whole = True
        todo = [start]
        while todo:
            sha = todo.pop()
            if sha in seen or (stop is not None and sha in stop):
                continue
            commit = index.get(sha)
            if commit is None:
                whole = False
                continue
            seen.add(sha)
            todo.extend(commit.parents_json or [])
        return seen, whole

    older, _ = walk(before) if before and before in index else (set(), False)
    newer, whole = walk(after, stop=older)
    out = _newest_first([index[s] for s in newer])
    complete = whole or (bool(before) and before in index)
    reason = "" if complete else "The kept history does not reach back to the earlier reading: fetch the history for every commit."
    return Between(out, complete, True, reason)


def _newest_first(commits: list[SourceCommit]) -> list[SourceCommit]:
    """
    As `git log` lists them: a commit always before its parents, and otherwise the
    newest first. Dates alone are not enough — two commits in the same second tie,
    and a rebased commit can be dated before its parent.
    """
    import heapq

    here = {c.sha: c for c in commits}
    children = {sha: 0 for sha in here}
    for c in commits:
        for p in c.parents_json or []:
            if p in children:
                children[p] += 1

    def key(c: SourceCommit) -> tuple[float, str]:
        return (-(c.authored_at.timestamp() if c.authored_at else 0.0), c.sha)

    ready = [(key(c), c.sha) for c in commits if children[c.sha] == 0]
    heapq.heapify(ready)
    out: list[SourceCommit] = []
    while ready:
        _, sha = heapq.heappop(ready)
        c = here[sha]
        out.append(c)
        for p in c.parents_json or []:
            if p in children:
                children[p] -= 1
                if children[p] == 0:
                    heapq.heappush(ready, (key(here[p]), p))
    return out


@dataclass(slots=True)
class FetchResult:
    ok: bool
    reason: str = ""
    commits: int = 0
    new: int = 0


@dataclass(slots=True)
class Step:
    """One reading, against the one before it."""

    reading: KnowledgeBase
    files: int
    previous: int | None = None
    #: Each kept: added, removed, modified, renamed; lines added and removed.
    changed: dict[str, int] = field(default_factory=dict)
    added: int = 0
    removed: int = 0
    #: The parts with the most lines changed, most first.
    parts: list[str] = field(default_factory=list)
    commits: int | None = None
    commits_complete: bool = False
    #: Why there are no numbers: the files of one of the two were never kept.
    missing: list[int] = field(default_factory=list)


@dataclass(slots=True)
class FileStep:
    reading: KnowledgeBase
    #: `added`, `modified` or `removed` against the reading before.
    status: str
    previous: int | None


#: Comparisons of two readings never change: kept for the life of the process.
_STEP_CACHE: dict[tuple[int, int], tuple[dict[str, int], int, int, list[str]]] = {}


class HistoryService:
    def __init__(self, db: AsyncSession, project_id: int) -> None:
        self.db = db
        self.project_id = project_id

    async def readings(self) -> list[KnowledgeBase]:
        rows = await self.db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.project_id == self.project_id, KnowledgeBase.status.in_([str(s) for s in _COMPARABLE]))
            .order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
        )
        return list(rows.scalars())

    async def between(self, before: KnowledgeBase | None, after: KnowledgeBase) -> Between:
        from codelith.db.repositories.knowledge.commit_repo import CommitRepository

        kept = await CommitRepository(self.db).all(self.project_id)
        return between(kept, before.commit_sha if before else None, after.commit_sha)

    async def steps(self) -> list[Step]:
        """Every reading against the one before it, newest first."""
        from collections import Counter

        from codelith.db.repositories.knowledge.commit_repo import CommitRepository
        from codelith.knowledge.compare import CompareService

        readings = await self.readings()
        counts = await self._file_counts([r.id for r in readings])
        kept = await CommitRepository(self.db).all(self.project_id)
        compare = CompareService(self.db)
        out: list[Step] = []
        for i, kb in enumerate(readings):
            prev = readings[i + 1] if i + 1 < len(readings) else None
            step = Step(reading=kb, files=counts.get(kb.id, 0), previous=prev.id if prev else None)
            if prev is not None:
                if kept:
                    b = between(kept, prev.commit_sha, kb.commit_sha)
                    if b.known:
                        step.commits, step.commits_complete = len(b.commits), b.complete
                key = (prev.id, kb.id)
                if key not in _STEP_CACHE:
                    if not counts.get(prev.id) or not counts.get(kb.id):
                        step.missing = [r.id for r in (prev, kb) if not counts.get(r.id)]
                    else:
                        cmp = await compare.files(prev, kb)
                        if cmp.available:
                            lines: Counter[str] = Counter()
                            for f in cmp.files:
                                if f.part:
                                    lines[f.part] += f.added + f.removed
                            _STEP_CACHE[key] = (
                                dict(Counter(f.status for f in cmp.files)),
                                cmp.added,
                                cmp.removed,
                                [p for p, _ in lines.most_common(4)],
                            )
                if key in _STEP_CACHE:
                    step.changed, step.added, step.removed, step.parts = _STEP_CACHE[key]
            out.append(step)
        return out

    async def file(self, path: str) -> list[FileStep]:
        """The readings where `path`'s content changed (or it appeared, or went), newest first."""
        readings = [r for r in await self.readings()]
        if not readings:
            return []
        rows = (
            await self.db.execute(
                select(ReadingFile.kb_id, ReadingFile.blob_hash).where(
                    ReadingFile.kb_id.in_([r.id for r in readings]), ReadingFile.path == path
                )
            )
        ).all()
        hashes = dict(rows)
        kept = await self._file_counts([r.id for r in readings])
        out: list[FileStep] = []
        older = list(reversed([r for r in readings if kept.get(r.id)]))
        for i, kb in enumerate(older):
            now = hashes.get(kb.id)
            was = hashes.get(older[i - 1].id) if i else None
            prev = older[i - 1].id if i else None
            if i == 0:
                if now is not None:
                    out.append(FileStep(kb, "added", None))
            elif now != was:
                out.append(FileStep(kb, "added" if was is None else "removed" if now is None else "modified", prev))
        return list(reversed(out))

    async def fetch(self) -> FetchResult:
        """Read the codebase's commits from its source, for readings taken before they were kept."""
        from codelith.db.repositories.knowledge.commit_repo import CommitRepository
        from codelith.ingestion.scratch import scratch_root
        from codelith.models.project import ProjectSource

        sources = (await self.db.execute(select(ProjectSource).where(ProjectSource.project_id == self.project_id))).scalars().all()
        source = next((s for s in sources if s.source_type in (*_HOSTED, "local")), None)
        if source is None:
            return FetchResult(False, "This codebase has no git source to read history from (an upload has none).")
        readings = await self.readings()
        latest = readings[0].commit_sha if readings else None

        import asyncio

        if source.source_type == "local":
            folder = Path(source.url_or_path).expanduser()
            rev = latest if latest and _git(folder, "cat-file", "-e", f"{latest}^{{commit}}", timeout=10) is not None else None
            commits = await asyncio.to_thread(read_commits, folder, rev)
            if commits is None:
                return FetchResult(False, "The folder is not a git repository, so it has no history to read.")
        else:
            dest = scratch_root() / str(uuid.uuid4())
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                cloned = await asyncio.to_thread(
                    _git, dest.parent, "clone", "--quiet", "--filter=blob:none", "--no-checkout", source.url_or_path, str(dest),
                    timeout=_CLONE_TIMEOUT,
                )
                if cloned is None:
                    return FetchResult(False, "The repository could not be cloned to read its history.")
                if latest and _git(dest, "cat-file", "-e", f"{latest}^{{commit}}", timeout=10) is None:
                    await asyncio.to_thread(_git, dest, "fetch", "--quiet", "--filter=blob:none", "origin", latest, timeout=_CLONE_TIMEOUT)
                rev = latest if latest and _git(dest, "cat-file", "-e", f"{latest}^{{commit}}", timeout=10) is not None else None
                commits = await asyncio.to_thread(read_commits, dest, rev) or []
            finally:
                shutil.rmtree(dest, ignore_errors=True)
        new = await CommitRepository(self.db).store(self.project_id, commits)
        await self.db.commit()
        logger.info("history_fetched", project_id=self.project_id, commits=len(commits), new=new)
        return FetchResult(True, "", len(commits), new)

    async def _file_counts(self, kb_ids: list[int]) -> dict[int, int]:
        from sqlalchemy import func

        if not kb_ids:
            return {}
        rows = await self.db.execute(
            select(ReadingFile.kb_id, func.count()).where(ReadingFile.kb_id.in_(kb_ids)).group_by(ReadingFile.kb_id)
        )
        return {int(k): int(n) for k, n in rows.all()}


__all__ = [
    "MAX_COMMITS",
    "Between",
    "Commit",
    "FetchResult",
    "FileStep",
    "HistoryService",
    "Step",
    "between",
    "parse_commits",
    "read_commits",
]
