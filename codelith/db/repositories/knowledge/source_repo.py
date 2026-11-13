"""
Each reading's files: written once by analysis, read by the code viewer and by every
comparison between two readings. See `codelith/models/source.py`.
"""

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.models.source import ReadingFile, SourceBlob

#: SQLite's default limit on bound variables is 999; stay well clear of it.
_BATCH = 400


def blob_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


@dataclass(slots=True)
class SnapshotFile:
    """One file as a reading keeps it."""

    path: str
    content: str
    language: str | None = None
    #: A project file's kind; `None` for source code.
    kind: str | None = None
    masked: bool = False


@dataclass(slots=True)
class StoredFile:
    """One file of a reading, without its content."""

    path: str
    hash: str
    language: str | None
    kind: str | None
    masked: bool
    size: int
    lines: int


@dataclass(slots=True)
class SnapshotStats:
    files: int = 0
    #: Blobs this write added: the content no reading on the machine had before.
    new_blobs: int = 0
    new_bytes: int = 0


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(self, kb_id: int, files: list[SnapshotFile]) -> SnapshotStats:
        """
        Keep these files as the reading's. Replaces whatever the reading held, so a
        reading taken again at the same commit does not end up with two lists.
        """
        stats = SnapshotStats()
        by_path: dict[str, tuple[SnapshotFile, str]] = {}
        for f in files:
            by_path[f.path] = (f, blob_hash(f.content))

        wanted = {h: f.content for f, h in by_path.values()}
        have: set[str] = set()
        hashes = list(wanted)
        for i in range(0, len(hashes), _BATCH):
            chunk = hashes[i : i + _BATCH]
            have.update((await self.session.execute(select(SourceBlob.hash).where(SourceBlob.hash.in_(chunk)))).scalars())
        for h, text in wanted.items():
            if h in have:
                continue
            raw = text.encode("utf-8", "replace")
            self.session.add(SourceBlob(hash=h, data=zlib.compress(raw, 6), size=len(raw), lines=_lines(text)))
            stats.new_blobs += 1
            stats.new_bytes += len(raw)
        await self.session.flush()

        await self.session.execute(delete(ReadingFile).where(ReadingFile.kb_id == kb_id))
        self.session.add_all(
            ReadingFile(kb_id=kb_id, path=path, blob_hash=h, language=f.language, kind=f.kind, masked=f.masked)
            for path, (f, h) in sorted(by_path.items())
        )
        await self.session.flush()
        stats.files = len(by_path)
        return stats

    async def has_snapshot(self, kb_id: int) -> bool:
        row = await self.session.execute(select(ReadingFile.id).where(ReadingFile.kb_id == kb_id).limit(1))
        return row.first() is not None

    async def files(self, kb_id: int, *, kinds: set[str] | None = None, project_only: bool = False) -> list[StoredFile]:
        """Every file of a reading, path order. `project_only` keeps the project files."""
        stmt = (
            select(
                ReadingFile.path,
                ReadingFile.blob_hash,
                ReadingFile.language,
                ReadingFile.kind,
                ReadingFile.masked,
                SourceBlob.size,
                SourceBlob.lines,
            )
            .join(SourceBlob, SourceBlob.hash == ReadingFile.blob_hash)
            .where(ReadingFile.kb_id == kb_id)
            .order_by(ReadingFile.path)
        )
        if kinds:
            stmt = stmt.where(ReadingFile.kind.in_(sorted(kinds)))
        elif project_only:
            stmt = stmt.where(ReadingFile.kind.is_not(None))
        return [
            StoredFile(path, h, language, kind, bool(masked), int(size or 0), int(lines or 0))
            for path, h, language, kind, masked, size, lines in await self.session.execute(stmt)
        ]

    async def manifest(self, kb_id: int) -> dict[str, str]:
        """Path to content hash, for comparing two readings without reading a file."""
        rows = await self.session.execute(
            select(ReadingFile.path, ReadingFile.blob_hash).where(ReadingFile.kb_id == kb_id)
        )
        return dict(rows.all())

    async def entry(self, kb_id: int, path: str) -> StoredFile | None:
        rows = await self.files_at(kb_id, [path])
        return rows.get(path)

    async def files_at(self, kb_id: int, paths: list[str]) -> dict[str, StoredFile]:
        out: dict[str, StoredFile] = {}
        for i in range(0, len(paths), _BATCH):
            chunk = paths[i : i + _BATCH]
            stmt = (
                select(
                    ReadingFile.path,
                    ReadingFile.blob_hash,
                    ReadingFile.language,
                    ReadingFile.kind,
                    ReadingFile.masked,
                    SourceBlob.size,
                    SourceBlob.lines,
                )
                .join(SourceBlob, SourceBlob.hash == ReadingFile.blob_hash)
                .where(ReadingFile.kb_id == kb_id, ReadingFile.path.in_(chunk))
            )
            for path, h, language, kind, masked, size, lines in await self.session.execute(stmt):
                out[path] = StoredFile(path, h, language, kind, bool(masked), int(size or 0), int(lines or 0))
        return out

    async def content(self, kb_id: int, path: str) -> str | None:
        """A file's text as this reading kept it, or `None` when it kept none."""
        row = (
            await self.session.execute(
                select(SourceBlob.data)
                .join(ReadingFile, ReadingFile.blob_hash == SourceBlob.hash)
                .where(ReadingFile.kb_id == kb_id, ReadingFile.path == path)
            )
        ).first()
        return zlib.decompress(row[0]).decode("utf-8", "replace") if row else None

    async def text(self, blob: str) -> str | None:
        row = (await self.session.execute(select(SourceBlob.data).where(SourceBlob.hash == blob))).first()
        return zlib.decompress(row[0]).decode("utf-8", "replace") if row else None

    async def usage(self, project_id: int | None = None) -> dict[str, int]:
        """Stored bytes, compressed and not, across the machine or for one codebase."""
        from codelith.models.knowledge import KnowledgeBase

        used = select(ReadingFile.blob_hash).distinct()
        if project_id is not None:
            used = used.join(KnowledgeBase, KnowledgeBase.id == ReadingFile.kb_id).where(
                KnowledgeBase.project_id == project_id
            )
        row = (
            await self.session.execute(
                select(func.count(), func.coalesce(func.sum(SourceBlob.size), 0), func.coalesce(func.sum(func.length(SourceBlob.data)), 0)).where(
                    SourceBlob.hash.in_(used.scalar_subquery())
                )
            )
        ).one()
        return {"blobs": int(row[0]), "bytes": int(row[1]), "stored_bytes": int(row[2])}

    async def prune(self, project_id: int, keep: int) -> int:
        """
        Drop the file lists of a codebase's readings beyond the newest `keep` that have
        them. Returns how many readings lost theirs; `sweep` then frees the content.
        """
        from codelith.models.knowledge import KnowledgeBase

        if keep <= 0:
            return 0
        with_files = (
            await self.session.execute(
                select(KnowledgeBase.id)
                .where(KnowledgeBase.project_id == project_id, KnowledgeBase.id.in_(select(ReadingFile.kb_id).distinct()))
                .order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
            )
        ).scalars().all()
        old = list(with_files[keep:])
        if old:
            await self.session.execute(delete(ReadingFile).where(ReadingFile.kb_id.in_(old)))
            await self.session.flush()
        return len(old)

    async def sweep(self) -> int:
        """Remove content no reading uses any more. Returns how many blobs went."""
        used = select(ReadingFile.blob_hash).distinct().scalar_subquery()
        result = await self.session.execute(delete(SourceBlob).where(SourceBlob.hash.not_in(used)))
        await self.session.flush()
        return int(result.rowcount or 0)


__all__ = ["SnapshotFile", "SnapshotStats", "SourceRepository", "StoredFile", "blob_hash"]
