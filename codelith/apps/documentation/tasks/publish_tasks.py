"""
Building a publication, as a job.

A job rather than a request handler for two reasons. It writes files, so it belongs
on the worker thread with everything else that does; and it gives the studio progress
for free, because `job_steps` and the agent log are already what `PipelineTree` and
the SSE stream read. No new progress machinery, no second way of watching work.

The order of the last two stages is the whole safety story. Files are written into a
directory nothing points at yet, checked while nothing points at them, and only then
does one row update make them the site. A build that fails at any stage leaves the
previous one serving, because the pointer never moved.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from codelith.apps.documentation.publishing import paths
from codelith.apps.documentation.publishing.renderers import get_renderer
from codelith.apps.documentation.publishing.verify import verify_build
from codelith.core.cancellation import JobCancelled
from codelith.db.session import AsyncSessionLocal
from codelith.workers import runner
from codelith.workers.task import task

logger = structlog.get_logger(__name__)

#: The stages, in order, named for what they do rather than for the code that does
#: it. They appear in the studio exactly like this.
STAGES = ("resolve", "render", "verify", "activate")


@task("publish.build_site")
def publish_site_task(job_id: int, publication_id: int, build_id: int) -> dict:
    return runner.run(_publish(job_id, publication_id, build_id))


async def _publish(job_id: int, publication_id: int, build_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        from codelith.apps.documentation.services.publication_service import PublicationService
        from codelith.db.repositories.job_repo import JobRepository
        from codelith.db.repositories.publication_repo import (
            PublicationBuildRepository,
            PublicationRepository,
        )
        from codelith.models.publication import BuildStatus, LIVE_TARGET, PublicationStatus

        jobs = JobRepository(db)
        pubs = PublicationRepository(db)
        builds = PublicationBuildRepository(db)
        progress = _Progress(db, job_id)

        publication = await pubs.get_by_id(publication_id)
        build = await builds.get_by_id(build_id)
        if publication is None or build is None:
            raise ValueError(f"Publication {publication_id} or build {build_id} is gone")

        out_dir = paths.build_dir(publication_id, build_id)

        try:
            await jobs.update(job_id, status="running", started_at=datetime.now(UTC))
            await db.commit()

            # ── resolve ──────────────────────────────────────────────────────
            await progress.start("resolve")
            service = PublicationService(db)
            owner = await _owner(db, publication)
            tree = await service.site_service.export_tree(
                publication.project_id,
                owner,
                None if publication.target == LIVE_TARGET else publication.target,
            )
            pages = sum(len(s.pages) for s in tree.sections)
            await progress.done("resolve", {"pages": pages, "sections": len(tree.sections)})

            # ── render ───────────────────────────────────────────────────────
            await progress.start("render")
            renderer = get_renderer(build.renderer)
            out_dir.mkdir(parents=True, exist_ok=True)
            result = renderer.build(tree, out_dir)
            await progress.done(
                "render",
                {"files": result.file_count, "bytes": result.bytes_total, "pages": result.page_count},
            )

            # ── verify ───────────────────────────────────────────────────────
            await progress.start("verify")
            report = verify_build(out_dir)
            await progress.done("verify", report.as_dict())
            if not report.ok:
                raise ValueError(_verify_message(report))

            # ── activate ─────────────────────────────────────────────────────
            # One row update. Before it, nothing reaches these files; after it,
            # everything does. There is no state in between.
            await progress.start("activate")
            build.status = BuildStatus.SUCCEEDED
            build.file_count = result.file_count
            build.bytes_total = result.bytes_total
            build.page_count = result.page_count
            build.verify_json = report.as_dict()
            build.finished_at = datetime.now(UTC)

            publication.current_build_id = build.id
            publication.status = PublicationStatus.LIVE
            publication.published_at = datetime.now(UTC)

            await jobs.update(job_id, status="completed", completed_at=datetime.now(UTC))
            await db.commit()
            await progress.done("activate", {"slug": publication.slug})

            # Only once the new build is live, so a prune that fails cannot take the
            # publish with it.
            pruned = await service.prune(publication_id)
            await db.commit()

            logger.info(
                "publication_built",
                publication_id=publication_id,
                build_id=build_id,
                files=result.file_count,
                bytes=result.bytes_total,
                pruned=pruned,
            )
            return {"publication_id": publication_id, "build_id": build_id, "slug": publication.slug}

        except JobCancelled:
            # Never downgraded to "this stage failed". A cancelled publish leaves the
            # previous build serving and takes its own half-written directory away.
            await _abandon(db, jobs, job_id, publication, build, out_dir, BuildStatus.CANCELLED, None)
            await progress.fail("activate", "cancelled")
            raise

        except Exception as exc:
            await _abandon(db, jobs, job_id, publication, build, out_dir, BuildStatus.FAILED, str(exc))
            await progress.fail(progress.current or "render", str(exc))
            logger.error(
                "publication_build_failed",
                publication_id=publication_id,
                build_id=build_id,
                error=str(exc),
            )
            raise


async def _abandon(
    db, jobs, job_id: int, publication, build, out_dir, status: str, error: str | None
) -> None:
    """
    Put everything back the way it was.

    The pointer is not touched, so whatever was live stays live. The directory goes,
    because a build that never became current is unreachable and only takes up room.
    """
    from codelith.models.publication import BuildStatus, PublicationStatus

    build.status = status
    build.error = error
    build.finished_at = datetime.now(UTC)

    # A publication that has never had a successful build has nothing to fall back on
    # and should say so. One that has stays live on the build it already had.
    if publication.current_build_id is None:
        publication.status = PublicationStatus.FAILED

    await jobs.update(
        job_id,
        status="cancelled" if status == BuildStatus.CANCELLED else "failed",
        completed_at=datetime.now(UTC),
    )
    await db.commit()
    paths.remove_tree(out_dir)


async def _owner(db, publication):
    """
    The user the site is read as.

    Publishing runs on a worker thread with no request behind it, so the reader is
    whoever asked for the publication. If that account is gone the build stops rather
    than falling back to some other user: which account a site was published as is
    the whole of its authorisation, and guessing at it would publish pages nobody
    living has the right to read.
    """
    from codelith.db.repositories.user_repo import UserRepository

    if publication.created_by:
        user = await UserRepository(db).get_by_id(publication.created_by)
        if user is not None:
            return user
    raise ValueError("The account that requested this publication no longer exists")


def _verify_message(report) -> str:
    """Why the build was refused, in the words the studio will show."""
    if report.external:
        first = report.external[0]
        return (
            f"The built site reaches outside this machine ({len(report.external)} "
            f"reference{'s' if len(report.external) > 1 else ''}, first: {first}). "
            "Nothing published may load from the network."
        )
    first = report.broken[0]
    return (
        f"The built site has {len(report.broken)} broken "
        f"link{'s' if len(report.broken) > 1 else ''} (first: {first})."
    )


class _Progress:
    """
    Stage rows, written the way agents write them.

    A separate small object rather than lines inline, because every stage needs the
    same three writes and the interesting code is the build, not the bookkeeping.
    """

    def __init__(self, db, job_id: int) -> None:
        self.db = db
        self.job_id = job_id
        self.current: str | None = None

    async def start(self, name: str) -> None:
        self.current = name
        await self._write(name, "running", started=True)
        await self._log("info", f"{name}: started")

    async def done(self, name: str, output: dict | None = None) -> None:
        await self._write(name, "completed", output=output, finished=True)
        await self._log("info", f"{name}: complete")

    async def fail(self, name: str, error: str) -> None:
        await self._write(name, "failed", output={"error": error}, finished=True)
        await self._log("error", f"{name}: {error}")

    async def _write(self, name, status, *, output=None, started=False, finished=False) -> None:
        from codelith.db.repositories.job_repo import JobStepRepository

        repo = JobStepRepository(self.db)
        timing = {}
        if started:
            timing["started_at"] = datetime.now(UTC)
        if finished:
            timing["completed_at"] = datetime.now(UTC)

        existing = await repo.list(job_id=self.job_id, agent_name=name)
        if existing:
            for step in existing:
                await repo.update(step.id, status=status, output_json=output or {}, **timing)
        else:
            await repo.create(
                job_id=self.job_id,
                agent_name=name,
                status=status,
                input_json={},
                output_json=output or {},
                **timing,
            )
        await self.db.commit()

    async def _log(self, level: str, message: str) -> None:
        from codelith.db.repositories.job_repo import AgentLogRepository

        await AgentLogRepository(self.db).create(
            job_id=self.job_id, agent_name="publisher", level=level, message=message
        )
        await self.db.commit()


__all__ = ["STAGES", "publish_site_task"]
