"""
Getting the repository back on disk.

Analysis clones, reads, and discards. Documentation and Ask never notice, because they
work entirely from the knowledge base. QA cannot: ruff and mypy take files, not
embeddings.

**Reconstructing from chunks was considered and rejected.** Chunks are stored per
symbol, so module-level code between them is simply absent — measured while extracting
environment variables, a file reconstructed from its chunks was missing five real
`os.getenv` calls that the original contained. Handing a linter a lossy copy produces
findings about code the author never wrote, which is worse than no findings.

So it re-clones, and the cost is stated rather than hidden: this is why QA is a job
that takes a while and not a page that loads.

**The commit is not pinned yet, and that is a known gap.** `CloneResult` carries the
SHA it landed on but the ingesters take a branch, not a revision — so a re-clone gets
the branch head, which may have moved past the analysed commit. The checkout reports
both, and callers say so rather than pretending the findings line up with the knowledge
base exactly.
"""

from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import structlog

from codelith.ingestion.pipeline import _INGESTER_MAP

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class Checkout:
    path: Path
    commit_sha: str | None
    #: The commit the knowledge base was built from.
    analysed_sha: str | None
    file_count: int = 0

    @property
    def matches_analysis(self) -> bool:
        """Whether the files on disk are the ones the knowledge base describes."""
        return bool(
            self.commit_sha and self.analysed_sha and self.commit_sha == self.analysed_sha
        )

    @property
    def drift_note(self) -> str:
        """What to tell a reader when they do not match. Empty when they do."""
        if self.matches_analysis or not self.commit_sha:
            return ""
        return (
            f"Checked at {self.commit_sha[:8]}, which is not the commit the knowledge "
            f"base was built from ({(self.analysed_sha or 'unknown')[:8]}). Findings "
            "are current; their impact is computed from the older analysis."
        )


@asynccontextmanager
async def checkout(project, analysed_sha: str | None = None):
    """
    Put the project's first source on disk, and take it away afterwards.

    Only the first source. A project with several is rare, the tools want one root,
    and guessing which of three to lint would be a worse answer than saying so.

    Cleanup is best-effort: a linter that left a file handle open makes `rmtree` fail
    on Windows, and losing a temporary directory is not worth failing a QA run over.
    """
    sources = list(getattr(project, "sources", None) or [])
    if not sources:
        raise ValueError("This codebase has no source to check out.")

    source = sources[0]
    ingester_cls = _INGESTER_MAP.get(source.source_type)
    if ingester_cls is None:
        raise ValueError(f"Cannot check out a '{source.source_type}' source.")

    result = await ingester_cls().clone(source.url_or_path, branch=source.branch)
    checked_out = Checkout(
        path=result.local_path,
        commit_sha=result.commit_sha,
        analysed_sha=analysed_sha,
        file_count=result.file_count,
    )
    logger.info(
        "qa_checkout",
        path=str(result.local_path),
        commit=result.commit_sha,
        matches_analysis=checked_out.matches_analysis,
    )
    try:
        yield checked_out
    finally:
        # A local source is the user's own working tree, not a copy — deleting it
        # would delete their code.
        if source.source_type != "local":
            shutil.rmtree(result.local_path, ignore_errors=True)


__all__ = ["Checkout", "checkout"]
