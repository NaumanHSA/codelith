"""
Applying a publish plan to a git working tree.

Deliberately thin, and deliberately stopping short of the network. `apply_plan`
writes files and commits them on a branch; pushing and opening a pull request are a
separate, explicitly-authorised step, because they are the two operations that leave
this machine.

That split is not caution for its own sake. The product's claim is that nothing
leaves the machine, and a feature that silently pushed a user's repository to a
forge would break that claim in the one place it matters most. Committing locally is
reversible and inspectable; pushing is neither.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog

from codelith.apps.documentation.services.repo_publish import PublishPlan

logger = structlog.get_logger(__name__)

_TIMEOUT = 60


@dataclass(frozen=True, slots=True)
class PublishResult:
    branch: str
    commit: str | None
    files_written: int
    #: True when the plan was a no-op, which is the expected outcome of publishing
    #: twice without regenerating anything.
    nothing_to_do: bool = False


class GitError(RuntimeError):
    """A git command failed. Carries what was run, so the failure is actionable."""


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603 — fixed binary, arguments are ours
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"git {' '.join(args)}: {exc}") from exc
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {(result.stderr or result.stdout).strip()[:300]}")
    return result.stdout.strip()


def apply_plan(
    plan: PublishPlan,
    repo_root: Path | str,
    *,
    branch: str,
    message: str,
    author: str = "Codelith <noreply@codelith.local>",
) -> PublishResult:
    """
    Write the plan onto a new branch and commit it.

    Nothing is pushed. The branch is left in the working repository for a human to
    inspect, push, or delete.

    A plan with no writes returns without creating a branch — publishing twice
    without regenerating anything should leave no trace, not an empty commit and a
    dangling branch.
    """
    repo = Path(repo_root)
    if not (repo / ".git").exists():
        raise GitError(f"{repo} is not a git repository")

    if plan.is_empty:
        logger.info("publish_noop", docs_dir=plan.docs_dir)
        return PublishResult(branch=branch, commit=None, files_written=0, nothing_to_do=True)

    original = _current_branch(repo)
    _git(repo, "checkout", "-B", branch)

    written = 0
    try:
        for change in plan.writes:
            path = repo / change.path
            path.parent.mkdir(parents=True, exist_ok=True)
            # Newline-normalised on write so a publish from Windows does not show
            # every line of every file as changed on a Unix forge.
            path.write_text(change.content, encoding="utf-8", newline="\n")
            written += 1

        _git(repo, "add", "--", plan.docs_dir)
        # `--porcelain` is empty when the working tree matches the index: the files
        # were written but identical, so there is nothing to commit.
        if not _git(repo, "status", "--porcelain", "--", plan.docs_dir):
            _git(repo, "checkout", original)
            return PublishResult(branch=branch, commit=None, files_written=written, nothing_to_do=True)

        _git(repo, "-c", f"user.name={author.split('<')[0].strip()}",
             "-c", f"user.email={_email(author)}",
             "commit", "-m", message, "--", plan.docs_dir)
        commit = _git(repo, "rev-parse", "HEAD")
    except GitError:
        # Leave the repository on the branch it was on. A failed publish must not
        # strand somebody on a branch they did not create.
        try:
            _git(repo, "checkout", original)
        except GitError:  # pragma: no cover - the original branch may be gone
            pass
        raise

    logger.info("publish_committed", branch=branch, commit=commit[:8], files=written)
    return PublishResult(branch=branch, commit=commit, files_written=written)


def _current_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def _email(author: str) -> str:
    if "<" in author and ">" in author:
        return author.split("<", 1)[1].split(">", 1)[0]
    return "noreply@codelith.local"


__all__ = ["apply_plan", "PublishResult", "GitError"]
