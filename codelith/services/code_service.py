"""
Showing the code the knowledge base kept.

The product's whole claim is that it read the repository, and until now nothing in
it has ever shown a line of what it read. This is the surface that closes that gap,
and the interesting part is not the reading, it is the honesty.

**Reconstruction, not retrieval.** The clone is discarded when analysis ends, so
there is no file to open. What exists is a set of chunks with line spans, and they
neither tile the file nor stay out of each other's way: measured across both
projects on this machine, `livenessLoop.js` is 252 lines whose chunks cover 423,
and every file has somewhere between one and thirteen lines no chunk claims.

So a file is rebuilt line by line, and the rules are:

* **Only `code` chunks.** A `docstring` chunk carries the span of the symbol it
  describes and a two-line summary of it. Written at its declared start line, that
  summary lands where the function body should be. On `server/main.py` this was
  eight conflicting lines from three chunks, and zero once they were excluded.
* **A chunk contributes only within its own declared span.** Content and span agree
  on every `code` chunk measured, and clamping costs nothing when they do. When they
  ever disagree, dropping the overflow keeps a later chunk's correct text.
* **First writer wins.** Overlaps agree exactly, so this is arbitrary in practice.
  What matters is that it is deterministic.
* **Gaps are named, never closed.** A run of lines nothing covered comes back as a
  segment saying which lines are missing. Joining across it would print code in an
  order that does not exist in the file.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.db.repositories.knowledge.knowledge_base_repo import KnowledgeBaseRepository
from codelith.memory.sql_graph_store import SqlGraphStore
from codelith.memory.vector_store import VectorStore
from codelith.models.chunk import CodeChunk
from codelith.models.user import User
from codelith.schemas.code import (
    CodeSegment,
    FileEntry,
    FileOut,
    FileTreeOut,
    SymbolEntry,
)
from codelith.services.project_service import ProjectService

logger = structlog.get_logger(__name__)


def rebuild(chunks: list[CodeChunk], loc: int = 0) -> tuple[list[CodeSegment], int, int]:
    """
    One file's lines, from the chunks that survived analysis.

    Returns the segments in line order, the count of lines recovered and the count
    known to be missing. A caller that wants a string can join the `code` segments,
    but it should not: the gaps between them are real.
    """
    lines: dict[int, str] = {}
    declared = 0
    for chunk in chunks:
        start = chunk.start_line
        if start is None:
            continue
        body = chunk.content.splitlines()
        # The declared span is the ceiling. See the module docstring: a chunk whose
        # content runs past its own end line would otherwise overwrite the file's
        # next region with a copy of itself.
        # The -1 matters now that this is also a floor: three lines from line 1
        # end at 3, and start + len would claim a fourth that does not exist.
        last = chunk.end_line if chunk.end_line is not None else start + len(body) - 1
        # And it is also a floor on how long the file is. A chunk saying it covers
        # through line 75 while holding two lines is evidence line 75 exists; without
        # this the file would simply end early and read as complete.
        declared = max(declared, last)
        for offset, text in enumerate(body):
            number = start + offset
            if number > last:
                break
            lines.setdefault(number, text)

    if not lines:
        return [], 0, 0

    # A file whose parser counted more lines than any chunk reached is missing its
    # tail, and the tail is exactly the part a reader assumes they have seen.
    highest = max(max(lines), declared, loc)

    segments: list[CodeSegment] = []
    run_start: int | None = None
    run: list[str] = []
    gap_start: int | None = None
    missing = 0

    def close_code() -> None:
        nonlocal run_start, run
        if run_start is not None:
            segments.append(
                CodeSegment(
                    kind="code", start=run_start, end=run_start + len(run) - 1,
                    text="\n".join(run),
                )
            )
        run_start, run = None, []

    def close_gap(end: int) -> None:
        nonlocal gap_start
        if gap_start is not None:
            segments.append(CodeSegment(kind="gap", start=gap_start, end=end))
        gap_start = None

    for number in range(1, highest + 1):
        text = lines.get(number)
        if text is None:
            close_code()
            if gap_start is None:
                gap_start = number
            missing += 1
        else:
            close_gap(number - 1)
            if run_start is None:
                run_start = number
            run.append(text)
    close_code()
    close_gap(highest)

    return segments, len(lines), missing


class CodeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.projects = ProjectService(db)
        self.bases = KnowledgeBaseRepository(db)
        self.chunks = VectorStore(db)
        self.graph = SqlGraphStore(db)

    async def tree(self, project_id: int, user: User) -> FileTreeOut:
        """
        Every file the reading covered, whether or not its source survived.

        The two sources disagree and both are needed. `graph_files` knows language,
        size and symbols but only for files a language provider parsed; the chunk
        table holds content for those *and* for the markdown a parser never looked
        at. A tree built from either alone is missing something a reader would
        expect to find, so this is their union.
        """
        await self.projects.get(project_id, user)

        kb = await self.bases.get_latest_usable(project_id)
        if kb is None:
            return FileTreeOut(available=False)

        parsed = {row["path"]: row for row in await self.graph.file_inventory(project_id, kb.id)}
        indexed = {
            path: (language, total, code)
            for path, language, total, code in await self.chunks.indexed_paths(kb.id)
        }

        files: list[FileEntry] = []
        without_source = 0
        for path in sorted(set(parsed) | set(indexed)):
            meta = parsed.get(path) or {}
            language, _total, code_chunks = indexed.get(path, ("", 0, 0))
            has_source = code_chunks > 0
            if not has_source:
                without_source += 1
            files.append(
                FileEntry(
                    path=path,
                    language=(meta.get("language") or language or ""),
                    loc=int(meta.get("loc") or 0),
                    symbols=int(meta.get("symbols") or 0),
                    lines_indexed=0,
                    has_source=has_source,
                )
            )

        return FileTreeOut(
            available=bool(files),
            commit_sha=kb.commit_sha,
            files=files,
            without_source=without_source,
            total_loc=sum(f.loc for f in files),
        )

    async def file(self, project_id: int, path: str, user: User) -> FileOut | None:
        """
        One file, rebuilt, with its outline.

        `None` only when the project has never been analysed. A path that was seen
        but kept nothing comes back with `indexed=False` and no segments, because
        "we read this and have nothing to show you" and "no such file" are different
        answers and the page should be able to say which.
        """
        await self.projects.get(project_id, user)

        kb = await self.bases.get_latest_usable(project_id)
        if kb is None:
            return None

        inventory = {
            row["path"]: row for row in await self.graph.file_inventory(project_id, kb.id)
        }
        meta = inventory.get(path, {})
        loc = int(meta.get("loc") or 0)

        chunks = await self.chunks.chunks_for_file(kb.id, path)
        segments, indexed, missing = rebuild(chunks, loc)

        symbols = [
            SymbolEntry(
                name=row["name"] or (row["qname"] or "").rsplit(".", 1)[-1],
                qname=row["qname"] or "",
                kind=row["kind"] or "",
                line=int(row["line"] or 0),
                end_line=row["end_line"],
                visibility=row["visibility"] or "",
            )
            for row in await self.graph.symbols_in_file(project_id, path)
        ]

        return FileOut(
            path=path,
            language=(meta.get("language") or (chunks[0].language if chunks else "") or ""),
            loc=loc,
            commit_sha=kb.commit_sha,
            segments=segments,
            symbols=symbols,
            lines_indexed=indexed,
            lines_missing=missing,
            chunks=len(chunks),
            indexed=bool(chunks),
        )


__all__ = ["CodeService", "rebuild"]
