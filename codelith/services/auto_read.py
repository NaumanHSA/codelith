"""
Reading every commit, by itself.

A reading is now cheap after a small commit — it keeps whatever did not change (see
`knowledge/incremental.py`) — so it can happen on every commit instead of when someone
remembers to press Analyse. This is the loop that does it, inside the server: every few
seconds it asks each local codebase that has "read every commit" switched on where its
`HEAD` is, and starts a reading when that is a commit no reading has seen.

Local sources only. A hosted repository would need a request to its host every few
seconds; `codelith watch` and the git hook cover the machine where the code is written,
which is where commits happen.

Rules that keep it quiet:

- One reading at a time per codebase: while one is pending or running, it waits. When
  that finishes, the next check reads whatever `HEAD` is by then, so a burst of commits
  costs one reading, not one each.
- A commit is tried once per process. If its reading fails, it is not retried every
  few seconds for ever; the next commit, or a person, tries again.
- It never stops the server: any failure is logged and the loop carries on.

The switch lives in the source's `config_json` as `auto_read: {on, by, since}`. `by` is
the person who turned it on; readings start as them, which is whose permission they
need and whose name the run carries.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

#: Commits already handed to a reading, by project, in this process.
_attempted: dict[int, str] = {}


def is_on(source) -> bool:
    return bool(((source.config_json or {}).get("auto_read") or {}).get("on"))


def switch(source, on: bool, user_id: int) -> dict:
    """The source's config with auto-read set. A new dict: SQLAlchemy only notices a
    JSON column changed when it is given a different object."""
    config = dict(source.config_json or {})
    config["auto_read"] = {"on": on, "by": user_id, "since": datetime.now(UTC).isoformat()}
    return config


def local_head(path: str) -> str | None:
    """`HEAD` of a local repository, or None. Blocking; run it on a thread."""
    try:
        import git

        root = Path(path).expanduser().resolve()
        if not root.exists():
            return None
        return git.Repo(root, search_parent_directories=True).head.commit.hexsha
    except Exception:
        return None


async def tick(db: AsyncSession, head=local_head) -> list[int]:
    """
    One pass over every local codebase with auto-read on. Returns the projects a
    reading was started for. `head` is injectable so the rules can be tested without
    a repository.
    """
    from codelith.knowledge.constants import JobType
    from codelith.models.job import Job
    from codelith.models.knowledge import KnowledgeBase
    from codelith.models.project import ProjectSource
    from codelith.models.user import User
    from codelith.services.knowledge_service import KnowledgeService

    started: list[int] = []
    sources = (
        (await db.execute(select(ProjectSource).where(ProjectSource.source_type == "local")))
        .scalars()
        .all()
    )
    for source in sources:
        if not is_on(source):
            continue
        project_id = source.project_id
        current = await asyncio.to_thread(head, source.url_or_path)
        if not current or _attempted.get(project_id) == current:
            continue

        latest = (
            await db.execute(
                select(KnowledgeBase.commit_sha)
                .where(KnowledgeBase.project_id == project_id)
                .order_by(KnowledgeBase.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest == current:
            _attempted[project_id] = current
            continue

        busy = (
            await db.execute(
                select(Job.id)
                .where(
                    Job.project_id == project_id,
                    Job.job_type == str(JobType.ANALYSIS),
                    Job.status.in_(("pending", "running")),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if busy is not None:
            continue

        by = ((source.config_json or {}).get("auto_read") or {}).get("by")
        user = await db.get(User, by) if by else None
        if user is None:
            logger.warning("auto_read_no_user", project_id=project_id)
            continue

        _attempted[project_id] = current
        try:
            job = await KnowledgeService(db).start_analysis(project_id, user, force=False)
        except Exception as exc:
            logger.warning("auto_read_start_failed", project_id=project_id, error=str(exc))
            continue
        logger.info("auto_read_started", project_id=project_id, commit=current[:8], job_id=job.id)
        started.append(project_id)
    return started


async def run_forever(interval: float) -> None:
    """The loop the server runs. Cancelled at shutdown."""
    from codelith.db.session import AsyncSessionLocal

    while True:
        await asyncio.sleep(interval)
        try:
            async with AsyncSessionLocal() as db:
                await tick(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("auto_read_tick_failed", exc_info=True)


async def set_auto_read(db: AsyncSession, project_id: int, user, on: bool) -> dict:
    """
    Switch "read every commit" for a codebase. Local sources only: the loop asks git
    on this machine, and a hosted repository has no working copy here to ask.
    Returns the state the studio shows.
    """
    from fastapi import HTTPException

    from codelith.models.project import ProjectSource
    from codelith.services.project_service import ProjectService

    await ProjectService(db).get(project_id, user)  # authorises and 404s
    source = (
        await db.execute(
            select(ProjectSource).where(ProjectSource.project_id == project_id).order_by(ProjectSource.id).limit(1)
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="This codebase has no source attached.")
    if source.source_type != "local":
        raise HTTPException(
            status_code=422,
            detail="Reading every commit works for a folder on this machine. "
            "For a hosted repository, run `codelith watch` or `codelith hook install` where the code is written.",
        )
    source.config_json = switch(source, on, user.id)
    _attempted.pop(project_id, None)
    await db.commit()
    return state_of(source)


def state_of(source) -> dict:
    """What the studio shows about the switch."""
    available = source is not None and source.source_type == "local"
    return {
        "available": available,
        "on": bool(available and is_on(source)),
        "since": ((source.config_json or {}).get("auto_read") or {}).get("since") if available else None,
    }
