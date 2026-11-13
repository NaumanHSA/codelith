"""A codebase's readings, the files each one kept, and any two compared line by line."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from codelith.dependencies import CurrentUser, DbSession
from codelith.knowledge.compare import CompareService
from codelith.knowledge.constants import KBStatus
from codelith.models.knowledge import KnowledgeBase
from codelith.models.source import ReadingFile
from codelith.services.project_service import ProjectService
from codelith.services.snapshot_service import SnapshotService

router = APIRouter(prefix="/projects", tags=["Readings"])

#: Readings that finished, well or not: the ones there is anything to compare.
_COMPARABLE = (KBStatus.READY, KBStatus.STALE, KBStatus.DEGRADED)


class ReadingOut(BaseModel):
    id: int
    commit: str | None
    status: str
    created_at: str
    #: Files the reading kept; 0 for one taken before readings kept their files.
    files: int = 0


class FillOut(BaseModel):
    ok: bool
    reason: str = ""
    files: int = 0
    project_files: int = 0
    new_blobs: int = 0


class FileChangeOut(BaseModel):
    path: str
    status: str
    old_path: str | None = None
    added: int = 0
    removed: int = 0
    language: str | None = None
    kind: str | None = None
    large: bool = False
    similarity: float | None = None
    part: str | None = None
    reach: int = 0
    direct: int = 0
    tests: int = 0
    pages: int = 0


class ComparisonOut(BaseModel):
    available: bool
    reason: str = ""
    before: ReadingOut | None = None
    after: ReadingOut | None = None
    missing: list[int] = Field(default_factory=list)
    files: list[FileChangeOut] = Field(default_factory=list)
    added: int = 0
    removed: int = 0


class RowOut(BaseModel):
    kind: str
    old: int | None = None
    new: int | None = None
    text: str
    marks: list[tuple[int, int]] = Field(default_factory=list)


class FileDiffOut(BaseModel):
    path: str
    old_path: str | None = None
    status: str
    language: str | None = None
    rows: list[RowOut] = Field(default_factory=list)
    whole: bool = True
    old_lines: int = 0
    new_lines: int = 0
    masked: bool = False


async def reading(db, project_id: int, kb_id: int) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None or kb.project_id != project_id:
        raise HTTPException(status_code=404, detail="No such reading of this codebase.")
    return kb


async def _readings(db, project_id: int) -> list[ReadingOut]:
    kbs = (
        await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.project_id == project_id, KnowledgeBase.status.in_([str(s) for s in _COMPARABLE]))
            .order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
        )
    ).scalars().all()
    counts = dict(
        (
            await db.execute(
                select(ReadingFile.kb_id, func.count())
                .where(ReadingFile.kb_id.in_([kb.id for kb in kbs]))
                .group_by(ReadingFile.kb_id)
            )
        ).all()
    )
    return [
        ReadingOut(
            id=kb.id,
            commit=kb.commit_sha,
            status=str(kb.status),
            created_at=kb.created_at.isoformat(),
            files=int(counts.get(kb.id, 0)),
        )
        for kb in kbs
    ]


async def _pair(db, project_id: int, before: int | None, after: int | None) -> tuple[KnowledgeBase, KnowledgeBase]:
    """The two readings to compare: as asked, or the latest and the one before it."""
    listed = await _readings(db, project_id)
    if after is None:
        if not listed:
            raise HTTPException(status_code=409, detail="This codebase has not been read yet.")
        after = listed[0].id
    if before is None:
        older = [r for r in listed if r.id != after]
        position = next((i for i, r in enumerate(listed) if r.id == after), 0)
        older = [r for r in listed[position + 1 :]] or older
        if not older:
            raise HTTPException(status_code=409, detail="This codebase has been read once: there is nothing to compare yet.")
        before = older[0].id
    return await reading(db, project_id, before), await reading(db, project_id, after)


@router.get("/{project_id}/readings", response_model=list[ReadingOut])
async def readings(project_id: int, db: DbSession, user: CurrentUser) -> list[ReadingOut]:
    """Every finished reading, newest first, with how many files each kept."""
    await ProjectService(db).get(project_id, user)
    return await _readings(db, project_id)


@router.post("/{project_id}/readings/{kb_id}/files", response_model=FillOut)
async def fetch_files(project_id: int, kb_id: int, db: DbSession, user: CurrentUser) -> FillOut:
    """
    Keep the files of a reading taken before readings kept them, fetched from git at
    the reading's commit. Nothing else about the reading changes.
    """
    await ProjectService(db).get(project_id, user)
    result = await SnapshotService(db).fill(await reading(db, project_id, kb_id))
    return FillOut(
        ok=result.ok,
        reason=result.reason,
        files=result.files,
        project_files=result.project_files,
        new_blobs=result.new_blobs,
    )


@router.get("/{project_id}/compare", response_model=ComparisonOut)
async def compare(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    before: int | None = None,
    after: int | None = None,
) -> ComparisonOut:
    """
    The files that changed between two readings, each with lines added and removed and
    what the reading knows about it. Defaults to the latest reading and the one before.
    """
    await ProjectService(db).get(project_id, user)
    earlier, later = await _pair(db, project_id, before, after)
    result = await CompareService(db).files(earlier, later)
    listed = {r.id: r for r in await _readings(db, project_id)}
    return ComparisonOut(
        available=result.available,
        reason=result.reason,
        before=listed.get(earlier.id),
        after=listed.get(later.id),
        missing=result.missing,
        files=[FileChangeOut(**{k: getattr(f, k) for k in FileChangeOut.model_fields}) for f in result.files],
        added=result.added,
        removed=result.removed,
    )


class CommitOut(BaseModel):
    sha: str
    author: str
    when: str | None = None
    subject: str
    files: list[str] = Field(default_factory=list)
    merge: bool = False


class CommitsOut(BaseModel):
    #: Commits are kept for the later reading's commit.
    known: bool
    #: Every commit between was kept.
    complete: bool
    reason: str = ""
    commits: list[CommitOut] = Field(default_factory=list)


class FetchHistoryOut(BaseModel):
    ok: bool
    reason: str = ""
    commits: int = 0
    new: int = 0


class StepOut(BaseModel):
    reading: ReadingOut
    previous: int | None = None
    changed: dict[str, int] = Field(default_factory=dict)
    added: int = 0
    removed: int = 0
    parts: list[str] = Field(default_factory=list)
    commits: int | None = None
    commits_complete: bool = False
    missing: list[int] = Field(default_factory=list)


class FileStepOut(BaseModel):
    reading: ReadingOut
    status: str
    previous: int | None = None


def _reading_out(kb: KnowledgeBase, files: int = 0) -> ReadingOut:
    return ReadingOut(id=kb.id, commit=kb.commit_sha, status=str(kb.status), created_at=kb.created_at.isoformat(), files=files)


def _commit_out(c) -> CommitOut:
    return CommitOut(
        sha=c.sha,
        author=c.author,
        when=c.authored_at.isoformat() if c.authored_at else None,
        subject=c.subject,
        files=list(c.files_json or []),
        merge=len(c.parents_json or []) > 1,
    )


@router.get("/{project_id}/compare/commits", response_model=CommitsOut)
async def compare_commits(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    before: int | None = Query(default=None),
    after: int | None = Query(default=None),
) -> CommitsOut:
    """The commits between two readings: reachable from the later one's commit, not the earlier one's."""
    from codelith.knowledge.history import HistoryService

    await ProjectService(db).get(project_id, user)
    old, new = await _pair(db, project_id, before, after)
    found = await HistoryService(db, project_id).between(old, new)
    return CommitsOut(known=found.known, complete=found.complete, reason=found.reason, commits=[_commit_out(c) for c in found.commits[:500]])


@router.post("/{project_id}/history/fetch", response_model=FetchHistoryOut)
async def fetch_history(project_id: int, db: DbSession, user: CurrentUser) -> FetchHistoryOut:
    """Read the codebase's commits from its source: for readings taken before commits were kept."""
    from codelith.knowledge.history import HistoryService

    await ProjectService(db).get(project_id, user)
    done = await HistoryService(db, project_id).fetch()
    return FetchHistoryOut(ok=done.ok, reason=done.reason, commits=done.commits, new=done.new)


@router.get("/{project_id}/history", response_model=list[StepOut])
async def history(project_id: int, db: DbSession, user: CurrentUser) -> list[StepOut]:
    """Every reading against the one before it: files and lines changed, the parts, the commits between."""
    from codelith.knowledge.history import HistoryService

    await ProjectService(db).get(project_id, user)
    return [
        StepOut(
            reading=_reading_out(s.reading, s.files),
            previous=s.previous,
            changed=s.changed,
            added=s.added,
            removed=s.removed,
            parts=s.parts,
            commits=s.commits,
            commits_complete=s.commits_complete,
            missing=s.missing,
        )
        for s in await HistoryService(db, project_id).steps()
    ]


@router.get("/{project_id}/file-history", response_model=list[FileStepOut])
async def file_history(
    project_id: int, db: DbSession, user: CurrentUser, path: str = Query(min_length=1, max_length=1000)
) -> list[FileStepOut]:
    """The readings where one file's content changed, newest first."""
    from codelith.knowledge.history import HistoryService

    await ProjectService(db).get(project_id, user)
    return [
        FileStepOut(reading=_reading_out(s.reading), status=s.status, previous=s.previous)
        for s in await HistoryService(db, project_id).file(path)
    ]


@router.get("/{project_id}/compare/file", response_model=FileDiffOut)
async def compare_file(
    project_id: int,
    db: DbSession,
    user: CurrentUser,
    path: str = Query(min_length=1, max_length=1000),
    before: int | None = None,
    after: int | None = None,
    old_path: str | None = Query(default=None, max_length=1000),
) -> FileDiffOut:
    """One file, line by line: every line, with the changed words within a line marked."""
    await ProjectService(db).get(project_id, user)
    earlier, later = await _pair(db, project_id, before, after)
    diff = await CompareService(db).file(earlier, later, path, old_path)
    if diff is None:
        raise HTTPException(status_code=404, detail="Neither reading has this file.")
    return FileDiffOut(
        path=diff.path,
        old_path=diff.old_path,
        status=diff.status,
        language=diff.language,
        rows=[RowOut(kind=r.kind, old=r.old, new=r.new, text=r.text, marks=r.marks) for r in diff.rows],
        whole=diff.whole,
        old_lines=diff.old_lines,
        new_lines=diff.new_lines,
        masked=diff.masked,
    )
