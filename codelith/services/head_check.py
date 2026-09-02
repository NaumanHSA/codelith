"""
Where the repository is now, without fetching it.

Analysis is the expensive thing this product does — clone, parse, embed, summarise,
minutes of a model's time — and the button that starts it gave no way to find out
whether it would produce anything new. Re-analysing a repository that has not moved
costs the same as re-analysing one that has, and produces a knowledge base identical
to the one already stored: `uq_kb_project_commit` means the same commit upserts rather
than becoming a second reading, so it does not even give *drift* a second point to
compare.

So this answers one question before the run starts: **has the code moved since the
last reading?**

`git ls-remote` for a hosted repository — one request, no clone, no working tree — and
`git rev-parse` for a local path. Both are fast enough to sit behind a dialog with a
spinner, which is the whole point: a check that takes as long as the thing it is
checking is not a check.

**Never blocks.** Every failure here — no network, a private repo without credentials,
git missing, a path that has gone — resolves to "could not tell", never to "do not
run". The operator asked to analyse; a check that cannot answer must not veto them.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

#: Long enough for a slow remote, short enough that a dialog does not feel hung. A
#: check that has not answered by now is one the operator should be allowed past.
_TIMEOUT_SECONDS = 12.0

#: Source types whose HEAD is a network lookup rather than a local one.
_REMOTE = ("github", "gitlab", "bitbucket")


@dataclass(slots=True)
class HeadCheck:
    """What is known about the repository's position, and how sure we are."""

    #: False when the current commit could not be determined at all.
    checked: bool
    #: True when the project has never been analysed — nothing to compare against,
    #: and the run is not a *re*-analysis.
    never_analysed: bool
    #: True when the run is expected to produce a new reading. Unknown counts as
    #: changed: the operator asked, and a check that failed must not stand in the way.
    changed: bool
    analysed_commit: str | None = None
    current_commit: str | None = None
    branch: str | None = None
    #: Why the check could not answer, in words the operator can act on.
    reason: str | None = None

    @property
    def short_analysed(self) -> str:
        return (self.analysed_commit or "")[:8]

    @property
    def short_current(self) -> str:
        return (self.current_commit or "")[:8]

    def summary(self) -> str:
        """The sentence the dialog leads with."""
        if self.never_analysed:
            return "This codebase has not been read yet. Analysis will build its first knowledge base."
        if not self.checked:
            return (
                "Could not tell whether the code has moved, so this may rebuild the "
                "reading you already have."
            )
        if not self.changed:
            return (
                f"The repository is still at {self.short_analysed}, the same commit as "
                "the last reading. Analysing again will rebuild the same knowledge "
                "base — it will not give drift a second point to compare."
            )
        return (
            f"The repository has moved on: {self.short_analysed} → {self.short_current}. "
            "Analysing will store a second reading, and drift can compare the two."
        )


async def head_check(
    *,
    source_type: str,
    url_or_path: str,
    branch: str | None,
    analysed_commit: str | None,
) -> HeadCheck:
    """
    Compare the repository's current HEAD against the commit last analysed.

    Returns rather than raises, always. See the module docstring: this informs a
    decision, it does not gate one.
    """
    if not analysed_commit:
        return HeadCheck(checked=True, never_analysed=True, changed=True, branch=branch)

    try:
        current = await asyncio.wait_for(
            asyncio.to_thread(_current_head, source_type, url_or_path, branch),
            timeout=_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        return HeadCheck(
            checked=False,
            never_analysed=False,
            changed=True,
            analysed_commit=analysed_commit,
            branch=branch,
            reason=f"The repository did not answer within {int(_TIMEOUT_SECONDS)} seconds.",
        )
    except Exception as exc:  # pragma: no cover - defensive; _current_head catches its own
        logger.warning("head_check_failed", error=str(exc))
        return HeadCheck(
            checked=False,
            never_analysed=False,
            changed=True,
            analysed_commit=analysed_commit,
            branch=branch,
            reason=str(exc)[:200],
        )

    if isinstance(current, str):
        return HeadCheck(
            checked=True,
            never_analysed=False,
            changed=current != analysed_commit,
            analysed_commit=analysed_commit,
            current_commit=current,
            branch=branch,
        )

    # `_current_head` hands back the failure rather than raising it — see its
    # docstring. Stringified here because `reason` is what a person reads, and an
    # exception object in a `str | None` field is a serialisation error at the API.
    return HeadCheck(
        checked=False,
        never_analysed=False,
        changed=True,
        analysed_commit=analysed_commit,
        branch=branch,
        reason=str(current),
    )


def _current_head(source_type: str, url_or_path: str, branch: str | None) -> str | Exception:
    """
    The commit the source is at now. Runs on a thread — git here is blocking.

    Returns the SHA, or an `Exception` carrying a sentence for the operator. Returning
    rather than raising keeps the "never blocks" rule in one place instead of spread
    across three except branches.
    """
    try:
        import git
    except Exception:  # pragma: no cover - git is a hard dependency of ingestion
        return RuntimeError("git is not available on this machine.")

    try:
        if source_type in _REMOTE:
            # No clone and no working tree: one request that asks the remote what it
            # has. `ls_remote` returns "<sha>\t<ref>" lines.
            ref = branch or "HEAD"
            raw = git.cmd.Git().ls_remote(url_or_path, ref)
            if not raw.strip() and branch:
                # A branch that no longer exists reads as an empty answer, which is a
                # different problem from a network failure and worth saying so.
                return RuntimeError(f"The remote has no branch '{branch}'.")
            if not raw.strip():
                return RuntimeError("The remote returned no HEAD.")
            return raw.split()[0]

        path = Path(url_or_path).expanduser().resolve()
        if not path.exists():
            return RuntimeError(f"The path no longer exists: {path}")
        return git.Repo(path, search_parent_directories=True).head.commit.hexsha
    except Exception as exc:
        return RuntimeError(_humanise(exc, source_type, url_or_path))


def _humanise(exc: Exception, source_type: str, url_or_path: str) -> str:
    """The failure as something to act on, not a git stack trace."""
    text = str(exc).lower()
    if "authentication" in text or "could not read username" in text or "403" in text:
        return "The repository needs credentials this machine does not have."
    if "not found" in text or "repository not found" in text or "404" in text:
        return f"The remote could not find {url_or_path}."
    if "could not resolve host" in text or "network" in text or "timed out" in text:
        return "Could not reach the remote — no network, or it is down."
    if source_type == "local":
        return "That path is not a git repository, so it has no commit to compare."
    return str(exc)[:200] or "The check failed for an unknown reason."


__all__ = ["HeadCheck", "head_check"]
