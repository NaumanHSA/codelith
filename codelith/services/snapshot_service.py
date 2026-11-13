"""
Keeping the files of a reading taken before readings kept them.

Analysis now keeps every reading's files (`reading_files`). Readings taken before
that hold only search chunks, so they can show no file whole and be compared with
nothing line by line. Their commit is recorded, though, and for a codebase in git
that is enough: the files at that commit are fetched, read exactly as analysis reads
them, and kept as the reading's. Nothing else about the reading changes.

**A folder of the user's is never changed.** A local source is read with
`git archive`, which writes the commit into a scratch folder of ours; a hosted one is
cloned there, without file contents until the one commit is checked out. The scratch
folder is removed when this finishes.
"""

from __future__ import annotations

import asyncio
import io
import shutil
import subprocess
import tarfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.db.repositories.knowledge.source_repo import SnapshotFile, SourceRepository
from codelith.ingestion.parsers.code_parser import CodeParser
from codelith.ingestion.scratch import scratch_root
from codelith.knowledge.detectors import read_project_files
from codelith.models.graph import GraphFile
from codelith.models.knowledge import KnowledgeBase
from codelith.models.project import ProjectSource

logger = structlog.get_logger(__name__)

_HOSTED = ("github", "gitlab", "bitbucket")
_GIT_TIMEOUT = 300


@dataclass(slots=True)
class FillResult:
    ok: bool
    reason: str = ""
    files: int = 0
    project_files: int = 0
    new_blobs: int = 0


def snapshot_files(code: list[tuple[str, str, str | None]], project) -> list[SnapshotFile]:
    """
    The files a reading keeps: its code `(path, content, language)` and its project
    files, the project file's kind and language winning where a path is both.
    """
    by_path = {p.path: p for p in project}
    out = [
        SnapshotFile(
            path=path,
            content=content or "",
            language=by_path[path].language if path in by_path else language,
            kind=by_path[path].kind if path in by_path else None,
            masked=by_path[path].masked if path in by_path else False,
        )
        for path, content, language in code
    ]
    seen = {f.path for f in out}
    out += [
        SnapshotFile(path=p.path, content=p.content, language=p.language, kind=p.kind, masked=p.masked)
        for p in project
        if p.path not in seen
    ]
    return out


def _git(args: list[str], cwd: Path | None = None, *, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.quotepath=off", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        timeout=_GIT_TIMEOUT,
        check=False,
        text=not binary,
    )


def _materialise(source: ProjectSource, commit: str, dest: Path) -> str | None:
    """Write the files of `commit` into `dest`. Returns why not, or `None`."""
    if source.source_type == "local":
        folder = Path(source.url_or_path).expanduser().resolve()
        top = _git(["rev-parse", "--show-toplevel"], folder)
        if top.returncode != 0:
            return "The folder is not a git repository, so its past commits cannot be read."
        prefix = folder.relative_to(Path(top.stdout.strip()).resolve()).as_posix()
        archive = _git(["archive", "--format=tar", commit, *([prefix] if prefix not in ("", ".") else [])], folder, binary=True)
        if archive.returncode != 0:
            return f"git could not read commit {commit[:8]} in this folder."
        dest.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(dest, filter="data")
        if prefix not in ("", "."):
            inner = dest / prefix
            staged = dest.with_name(dest.name + "-in")
            inner.rename(staged)
            shutil.rmtree(dest, ignore_errors=True)
            staged.rename(dest)
        return None

    if source.source_type in _HOSTED:
        clone = _git(["clone", "--filter=blob:none", "--no-checkout", "--quiet", source.url_or_path, str(dest)])
        if clone.returncode != 0:
            return "The repository could not be cloned."
        checkout = _git(["checkout", "--quiet", commit], dest)
        if checkout.returncode != 0:
            fetch = _git(["fetch", "--quiet", "--filter=blob:none", "origin", commit], dest)
            checkout = _git(["checkout", "--quiet", commit], dest) if fetch.returncode == 0 else fetch
        if checkout.returncode != 0:
            return f"Commit {commit[:8]} is no longer in the repository."
        return None
    return f"A {source.source_type} source has no history to read."


class SnapshotService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.sources = SourceRepository(db)

    async def fill(self, kb: KnowledgeBase) -> FillResult:
        if await self.sources.has_snapshot(kb.id):
            return FillResult(ok=True, reason="This reading already keeps its files.")
        if not kb.commit_sha:
            return FillResult(ok=False, reason="This reading has no commit to fetch.")
        sources = (
            await self.db.execute(select(ProjectSource).where(ProjectSource.project_id == kb.project_id))
        ).scalars().all()
        source = next((s for s in sources if s.source_type in (*_HOSTED, "local")), None)
        if source is None:
            return FillResult(ok=False, reason="This codebase has no git source to fetch the files from.")

        dest = scratch_root() / str(uuid.uuid4())
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            why = await asyncio.to_thread(_materialise, source, kb.commit_sha, dest)
            if why:
                return FillResult(ok=False, reason=why)
            parsed = await asyncio.to_thread(CodeParser().parse_directory, dest)
            project = await asyncio.to_thread(read_project_files, dest)
        except (OSError, subprocess.SubprocessError, tarfile.TarError) as exc:
            logger.warning("snapshot_fill_failed", kb_id=kb.id, error=f"{type(exc).__name__}: {exc}")
            return FillResult(ok=False, reason="The files at this commit could not be read.")
        finally:
            shutil.rmtree(dest, ignore_errors=True)

        files = snapshot_files([(f.path, f.content, f.language) for f in parsed.files], project)
        stats = await self.sources.store(kb.id, files)

        # The map lists files from the graph: add the project files analysis now adds.
        listed = set(
            (
                await self.db.execute(
                    select(GraphFile.path).where(GraphFile.project_id == kb.project_id, GraphFile.kb_id == kb.id)
                )
            ).scalars()
        )
        for p in project:
            if p.path not in listed:
                lines = p.content.count("\n") + (0 if p.content.endswith("\n") or not p.content else 1)
                self.db.add(
                    GraphFile(
                        project_id=kb.project_id,
                        kb_id=kb.id,
                        path=p.path,
                        language=p.language,
                        module_key=None,
                        loc=lines,
                    )
                )
        await self.db.commit()
        logger.info("snapshot_filled", kb_id=kb.id, files=stats.files, new_blobs=stats.new_blobs)
        return FillResult(ok=True, files=stats.files, project_files=len(project), new_blobs=stats.new_blobs)


__all__ = ["FillResult", "SnapshotService", "snapshot_files"]
