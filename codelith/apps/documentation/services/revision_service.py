"""
Starting and loading a revision.

Everything that can be refused is refused *here*, before a job exists and before any
model is called: a page that is being written, a heading that does not exist, an
anchor that matches two headings. A revision that fails at the API is a message; the
same revision failing inside a worker is a red job the user has to open and read.

The conversation the studio shows is not stored in a table of its own. Each turn is a
`revision` job carrying its anchor and its instruction, so the transcript for a
heading is a query over jobs — durable across reloads, and consistent with the
panel's rule that moving to another heading starts again.
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from codelith.apps.documentation.services.site_service import SiteService
from codelith.core.exceptions import NotFoundError, ValidationError
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.db.repositories.site_repo import DocPageRepository, DocSiteRepository
from codelith.knowledge.blocks import find_blocks, outline
from codelith.knowledge.constants import JobType, KBStatus, PageStatus
from codelith.models.job import Job
from codelith.models.user import User
from codelith.schemas.job import JobConfig, JobCreate
from codelith.services.job_service import JobService
from codelith.services.project_service import ProjectService

logger = structlog.get_logger(__name__)

#: Turns of history handed to the model. The panel is scoped to one heading and
#: cleared when the reader moves on, so this is short by construction; the cap is
#: only here so a very long session cannot quietly grow the prompt without bound.
MAX_HISTORY_TURNS = 6


class RevisionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.projects = ProjectService(db)
        self.jobs = JobService(db)
        self.sites = DocSiteRepository(db)
        self.pages = DocPageRepository(db)

    async def start(
        self,
        project_id: int,
        section_slug: str,
        slug: str,
        user: User,
        *,
        instructions: str,
        anchor: str | None = None,
    ) -> Job:
        """
        Queue a revision of one heading, or of a whole page.

        `anchor` is the `anchor_id` of a `##` heading — the same id the studio stamps
        on rendered headings and the linker validates fragment links against. Omit it
        to revise the entire page.
        """
        await self.projects.get(project_id, user)

        if not (instructions or "").strip():
            raise ValidationError("Say what should change — a revision needs instructions.")

        site = await self.sites.get_for_project(project_id)
        if site is None:
            raise NotFoundError("Documentation site for project", project_id)

        page = await self.pages.get_by_slug(site.id, section_slug, slug, version_id=None)
        if page is None:
            raise NotFoundError("Page", f"{section_slug}/{slug}")

        if not (page.content_markdown or "").strip():
            raise ValidationError(
                f"'{section_slug}/{slug}' has not been written yet. "
                "Write it first, then ask for changes."
            )
        if page.status == PageStatus.GENERATING:
            raise ValidationError(
                f"'{section_slug}/{slug}' is being written right now. "
                "Wait for that run to finish before revising it."
            )

        if anchor:
            # Resolved before the job exists, so an anchor that has gone — the page
            # was rewritten and lost that heading — is a message rather than a job
            # that fails two minutes later.
            matches = find_blocks(page.content_markdown or "", anchor)
            if not matches:
                available = ", ".join(s["anchor"] for s in outline(page.content_markdown or ""))
                raise ValidationError(
                    f"No section '{anchor}' on that page. It has: {available or '(none)'}."
                )
            if len(matches) > 1:
                raise ValidationError(
                    f"'{matches[0].title}' appears {len(matches)} times on this page, "
                    "so it cannot be addressed unambiguously. Rename one heading first."
                )

        kb = await self._usable_kb(project_id)
        address = f"{section_slug}/{slug}"
        depth = await self._depth_of(page)

        # The same scope shape a composition records, so the studio's job views —
        # "writing into", the target list, "Read the document" — work on a revision
        # without either side special-casing it.
        scope = await SiteService(self.db).describe_scope(project_id, [page])

        job = await self.jobs.create(
            project_id,
            JobCreate(
                config=JobConfig(
                    doc_types=[page.doc_type],
                    page_slugs=[address],
                    output_formats=["markdown"],
                    human_review=False,
                    # A rewrite of one section must not silently resize it. The page
                    # was written at some depth and the rest of it still is, so the
                    # revision inherits that rather than falling back to standard.
                    depth=depth,
                )
            ),
            user,
            job_type=JobType.REVISION,
            config_overrides={
                "kb_id": kb.id,
                "address": address,
                "section_slug": section_slug,
                "slug": slug,
                "anchor": anchor,
                "instructions": instructions.strip(),
            },
            scope=scope,
        )

        from codelith.apps.documentation.tasks.revision_tasks import run_revision
        from codelith.workers.dispatch import dispatch

        task_id = dispatch(run_revision, job.id)
        await self.jobs.start(job.id, task_id)
        logger.info(
            "revision_queued",
            job_id=job.id,
            project_id=project_id,
            address=address,
            anchor=anchor,
        )
        # Re-fetched rather than returned directly: `JobOut` serialises `project_name`
        # and `steps`, and a freshly created row has neither relationship loaded —
        # touching them during serialisation raises MissingGreenlet on an async session.
        return await self.jobs.get(job.id)

    async def load_target(self, job: Job) -> tuple[dict, dict]:
        """
        The page to revise and everything the reviser needs around it.

        Runs in the worker, so it re-checks what the API checked: between queueing and
        running, another job may have claimed the page.
        """
        config = job.config_json or {}
        site = await self.sites.get_for_project(job.project_id)
        if site is None:
            raise ValueError("The project has no documentation site")

        page = await self.pages.get_by_slug(
            site.id, config["section_slug"], config["slug"], version_id=None
        )
        if page is None:
            raise ValueError(f"Page {config.get('address')} no longer exists")

        kb_id = config.get("kb_id")
        kb = None
        if kb_id:
            kb = await KnowledgeRepositories.for_session(self.db).bases.get_with_children(kb_id)

        target = {
            "id": page.id,
            "address": f"{page.section_slug}/{page.slug}",
            "section_slug": page.section_slug,
            "slug": page.slug,
            "title": page.title,
            "intent": page.intent,
            "doc_type": page.doc_type,
            "content_markdown": page.content_markdown or "",
            "source_files": list(page.source_files_json or []),
            "key_files": list(page.key_files_json or []),
        }
        context = {
            "kb_id": kb_id,
            "commit_sha": kb.commit_sha if kb else page.commit_sha,
            "site_map": (kb.site_map_json if kb else {}) or {},
            "strategy": (kb.strategy_json if kb else {}) or {},
            "anchor": config.get("anchor"),
            "instructions": config.get("instructions") or "",
            "history": await self.history(job),
            # The publisher marks the page written against this job.
            "pages": [{"id": page.id, "address": target["address"]}],
        }
        return target, context

    async def transcript(
        self,
        project_id: int,
        section_slug: str,
        slug: str,
        user: User,
        anchor: str | None = None,
    ) -> list[Job]:
        """
        The revision turns against one heading, oldest first — the conversation.

        Every status is returned, not just the successful ones: a turn that failed is
        part of what was said, and hiding it would leave the reader wondering why the
        page did not change. The model is given only the completed ones (`history`).
        """
        await self.projects.get(project_id, user)
        address = f"{section_slug}/{slug}"

        rows = (
            await self.db.execute(
                select(Job)
                # Eager, because these rows are serialised as `JobOut` — which reads
                # `project_name` and `steps` off the relationships. Lazy-loading either
                # during serialisation raises MissingGreenlet on an async session.
                .options(selectinload(Job.steps), selectinload(Job.project))
                .where(Job.project_id == project_id, Job.job_type == JobType.REVISION)
                .order_by(desc(Job.id))
                .limit(60)
            )
        ).scalars().all()

        matching = [
            row
            for row in rows
            if (row.config_json or {}).get("address") == address
            and (row.config_json or {}).get("anchor") == anchor
        ]
        return list(reversed(matching))

    async def rekey_anchor(self, job: Job, new_anchor: str) -> int:
        """
        Move this heading's conversation onto its new anchor.

        A revision may rename the heading its own edit made inaccurate, and the anchor
        is the key every turn is stored under. Without this the transcript is stranded:
        reopening the renamed heading shows an empty conversation, and the next turn is
        given none of the history it was promised — measured, two turns orphaned by one
        rename.

        The renaming turn moves too, so it reads as part of the same thread rather than
        as the boundary between two.
        """
        config = job.config_json or {}
        address, old = config.get("address"), config.get("anchor")
        if not address or not old or old == new_anchor:
            return 0

        rows = (
            await self.db.execute(
                select(Job).where(
                    Job.project_id == job.project_id,
                    Job.job_type == JobType.REVISION,
                )
            )
        ).scalars().all()

        moved = 0
        for row in rows:
            cfg = row.config_json or {}
            if cfg.get("address") != address or cfg.get("anchor") != old:
                continue
            # Replaced wholesale: SQLAlchemy does not see a JSONB dict mutated in place.
            row.config_json = {**cfg, "anchor": new_anchor, "renamed_from": old}
            moved += 1

        await self.db.commit()
        logger.info(
            "revision_anchor_rekeyed",
            project_id=job.project_id,
            address=address,
            old=old,
            new=new_anchor,
            turns=moved,
        )
        return moved

    async def repoint_links(self, job: Job, old_anchor: str, new_anchor: str) -> list[str]:
        """
        Repoint links on *other* pages that named the heading before it was renamed.

        The linker only ever sees the pages a job is writing, so it can fix the
        revised page's own links and nothing else. A link from elsewhere in the site
        into the renamed heading is invisible to it and would stay stale until that
        page happened to be rewritten — which may be never.

        Repointed rather than stripped: the new anchor is known exactly, so the
        reference survives instead of degrading to a link that lands at the top of
        the page.

        `old_anchor` is a parameter rather than read off the job, because
        `rekey_anchor` moves this job's own `config_json.anchor` onto the new value —
        so by the time both have run, the job no longer records what the heading used
        to be called. Reading it here silently found nothing to repoint.
        """
        config = job.config_json or {}
        address, old = config.get("address"), old_anchor
        if not address or not old or old == new_anchor:
            return []

        site = await self.sites.get_for_project(job.project_id)
        if site is None:
            return []

        # Only the full route form: a bare `](#old)` on another page addresses *that*
        # page's heading, which this rename says nothing about.
        pattern = re.compile(
            rf"(\]\(/app/projects/\d+/docs/{re.escape(address)})#{re.escape(old)}\)"
        )

        touched: list[str] = []
        for page in await self.pages.list_for_site(site.id):
            if f"{page.section_slug}/{page.slug}" == address:
                continue  # The linker already repointed the revised page itself.
            content = page.content_markdown or ""
            updated, hits = pattern.subn(rf"\g<1>#{new_anchor})", content)
            if hits:
                page.content_markdown = updated
                touched.append(f"{page.section_slug}/{page.slug} ({hits})")

        if touched:
            await self.db.commit()
            logger.info(
                "revision_links_repointed",
                project_id=job.project_id,
                address=address,
                old=old,
                new=new_anchor,
                pages=touched,
            )
        return touched

    async def history(self, job: Job) -> list[dict]:
        """
        Earlier turns against the same heading, oldest first.

        Scoped to the anchor, not the page: the panel clears when the reader moves to
        another heading, and the model should not be told about a conversation the
        reader considers finished.
        """
        config = job.config_json or {}
        rows = (
            await self.db.execute(
                select(Job)
                .where(
                    Job.project_id == job.project_id,
                    Job.job_type == JobType.REVISION,
                    Job.id != job.id,
                )
                .order_by(desc(Job.id))
                .limit(40)
            )
        ).scalars().all()

        turns = [
            {
                "job_id": row.id,
                "instructions": (row.config_json or {}).get("instructions"),
                "status": row.status,
            }
            for row in rows
            if (row.config_json or {}).get("address") == config.get("address")
            and (row.config_json or {}).get("anchor") == config.get("anchor")
            and row.status == "completed"
        ]
        return list(reversed(turns))[-MAX_HISTORY_TURNS:]

    async def _depth_of(self, page) -> str:
        """
        The depth the page was written at.

        Read from the job that wrote it rather than stored on the page: `DocPage`
        already records `job_id`, and one lookup is cheaper than a migration for a
        value only this path needs. A rewritten heading must not silently come back
        half the length of the ones around it, which is what falling back to standard
        on a page written as `detailed` would do.

        Falls back to standard for a page written before depth existed, or by a path
        that recorded no job.
        """
        from codelith.apps.documentation import depth as depth_profile
        from codelith.models.job import Job

        if not page.job_id:
            return depth_profile.DEFAULT.value
        job = await self.db.get(Job, page.job_id)
        return ((job.config_json or {}).get("depth") if job else None) or (
            depth_profile.DEFAULT.value
        )

    async def _usable_kb(self, project_id: int):
        bases = KnowledgeRepositories.for_session(self.db).bases
        kb = await bases.get_latest_usable(project_id)
        if kb is None or not KBStatus(kb.status).can_serve_features:
            raise ValidationError(
                "This project has no usable knowledge base. Analyse it first — a "
                "revision is grounded in the same evidence the page was written from."
            )
        return kb


__all__ = ["RevisionService", "MAX_HISTORY_TURNS"]
