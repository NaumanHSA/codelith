"""
Clones are working files, and working files get thrown away.

Analysis clones a repository into `REPO_SCRATCH_DIR/<uuid>`, reads it, and builds a
knowledge base from what it read. Nothing needs the checkout afterwards — the file
viewer rebuilds a file from stored chunks, and says so in its own docstring: *"Analysis
discards the checkout, so there is no file to open."*

It did not discard it. Every analysis left a full copy behind, one per run rather than
one per project, and nothing ever removed them — not job completion, not project
deletion. Thirty runs of a medium repository is a couple of gigabytes of directories
nobody can name, in a tool whose pitch is that it runs on your own machine.

Two rules make removal safe, and both are enforced here rather than at the call site:

1. **Only paths this process created.** A `local` source is the user's own directory,
   passed straight through as `local_path` — deleting that would delete their code.
   The local ingester never registers anything, so it cannot be reached from here.
2. **Only inside the scratch root.** Registration is refused for anything that does not
   resolve to a direct child of `REPO_SCRATCH_DIR`, so a bug in a caller cannot turn
   this into a general-purpose delete.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from contextvars import ContextVar
from pathlib import Path
from uuid import UUID

import structlog

from codelith.config import get_settings

logger = structlog.get_logger(__name__)

#: Clones created during the current job. A context variable rather than an argument
#: threaded through the pipeline: the ingesters that create these directories sit four
#: calls below the task that has to clean them up, and every layer between would carry
#: a parameter it does not otherwise use.
_created: ContextVar[list[Path] | None] = ContextVar("codelith_scratch_clones", default=None)


def _force_writable(func, path, _exc) -> None:
    """
    Retry a delete that failed because the file was read-only.

    Git marks the files in `.git/objects/pack` read-only, and on Windows a read-only
    file cannot be unlinked — `PermissionError: [WinError 5] Access is denied`. Every
    clone has a `.git`, so without this the cleanup fails on the first pack file of
    the first directory and removes nothing at all on the platform. It failed exactly
    that way on 32 directories before this existed.

    POSIX does not need it (permission to unlink comes from the directory), and it
    costs nothing there because it only runs on the error path.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


#: `onerror` was replaced by `onexc` in 3.12 and warns there; 3.11 has only `onerror`.
#: The handler ignores its third argument, which is the only thing that differs.
_RMTREE_RETRY = (
    {"onexc": _force_writable} if sys.version_info >= (3, 12) else {"onerror": _force_writable}
)


def scratch_root() -> Path:
    return Path(get_settings().REPO_SCRATCH_DIR).resolve()


def _is_managed(path: Path) -> bool:
    """A direct child of the scratch root, named as one of ours."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if resolved.parent != scratch_root():
        return False
    try:
        UUID(resolved.name)
    except ValueError:
        # `uploads/` lives here too and holds the only copy of an uploaded archive.
        # Nothing but a clone is named as a UUID, so nothing but a clone is touched.
        return False
    return True


def track(path: Path) -> None:
    """Register a clone this process just made, for removal when the job ends."""
    if not _is_managed(path):
        logger.warning("scratch_track_refused", path=str(path))
        return
    clones = _created.get()
    if clones is None:
        clones = []
        _created.set(clones)
    clones.append(path.resolve())


def discard() -> int:
    """
    Remove every clone registered in this context. Returns how many went.

    Best effort by design, and called from a `finally`: a directory that will not
    delete is a disk-space problem, and raising here would turn it into a failed job
    for work that has already succeeded.
    """
    clones = _created.get()
    _created.set(None)
    if not clones:
        return 0

    gone = 0
    for path in clones:
        if not _is_managed(path) or not path.exists():
            continue
        try:
            shutil.rmtree(path, **_RMTREE_RETRY)
            gone += 1
        except OSError as exc:
            logger.warning("scratch_discard_failed", path=str(path), error=str(exc))
    if gone:
        logger.info("scratch_discarded", count=gone)
    return gone


def sweep() -> int:
    """
    Remove clones left by earlier runs. Returns how many went.

    Safe only where nothing can be mid-analysis, which is why it is called at startup
    and nowhere else: work runs on a thread inside this process, so a starting process
    owns no jobs and every clone under the root is from a run that is over. Installs
    that predate `discard` have all of theirs here.
    """
    root = scratch_root()
    if not root.is_dir():
        return 0

    gone = 0
    for child in root.iterdir():
        if not child.is_dir() or not _is_managed(child):
            continue
        try:
            shutil.rmtree(child, **_RMTREE_RETRY)
            gone += 1
        except OSError as exc:
            logger.warning("scratch_sweep_failed", path=str(child), error=str(exc))
    if gone:
        logger.info("scratch_swept", count=gone, root=str(root))
    return gone
