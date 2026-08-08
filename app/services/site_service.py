"""
The documentation site: reconciling what analysis proposes with what exists.

`merge_proposal` is the piece the whole incremental design rests on. Analysis plans
the entire site up front and re-plans it on every commit; composition fills it in a
section at a time, months apart. Those two facts only coexist because the merge
obeys three rules, and nothing else in the system is allowed to touch `doc_pages`
structurally:

    proposed, does not exist    → insert as `planned`
    proposed, exists            → keep it. Title may change; **the slug never does**
    exists, no longer proposed  → mark `orphaned`. Never delete

The third rule is the important one. A slug is a URL, a bookmark, an internal
`[[page-slug]]` link target and the key this merge matches on. Deleting a page
because one analysis run stopped proposing it would break all four, silently, and
the run that stopped proposing it is as likely to be a bad LLM call as a real change
to the codebase.

`pinned` is the escape hatch for the user: a page or section renamed or reordered by
hand is left alone by the merge, and survives even when it drops out of a proposal.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.db.repositories.knowledge import KnowledgeRepositories
from app.db.repositories.site_repo import (
    DocPageRepository,
    DocSiteRepository,
    DocSiteVersionRepository,
)
from app.formatters.site_tree import (
    ExportPage,
    ExportSection,
    SiteTree,
    rewrite_links,
    slugify_filename,
)
from app.knowledge.constants import NarrativeTopic, PageStatus
from app.models.site import DocPage, DocSite
from app.models.user import User
from app.schemas.site import (
    SiteOut,
    SitePageDetail,
    SitePageOut,
    SiteSectionOut,
    SiteVersionOut,
)
from app.services.project_service import ProjectService

#: Page columns the merge may rewrite from a proposal. `slug` and `section_slug` are
#: absent by design — they are the identity of the row, not a property of it — and so
#: is everything composition owns (`content_markdown`, `status`, provenance).
_MERGEABLE = ("doc_type", "intent", "key_files_json", "confidence", "reason")

#: Additionally rewritten, but only on a page the user has not pinned.
_MERGEABLE_UNPINNED = ("title", "order_index")


@dataclass(slots=True)
class MergeCounts:
    site_id: int = 0
    inserted: int = 0
    updated: int = 0
    orphaned: int = 0
    restored: int = 0
    sections: int = 0
    total_pages: int = 0
    #: Slugs touched, for the trace artifact — a merge that renames nothing should
    #: be visible as such rather than inferred from counts.
    inserted_slugs: list[str] = field(default_factory=list)
    orphaned_slugs: list[str] = field(default_factory=list)


logger = structlog.get_logger(__name__)


class SiteService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.sites = DocSiteRepository(db)
        self.pages = DocPageRepository(db)
        self.versions = DocSiteVersionRepository(db)
        self.projects = ProjectService(db)

    # ── Merge ─────────────────────────────────────────────────────────────────

    async def merge_proposal(
        self, project_id: int, site_map: dict, *, kb_id: int | None = None
    ) -> MergeCounts:
        """
        Fold one analysis proposal into the project's site.

        Idempotent: merging the same map twice reports zero changes the second time,
        because every write is dirty-checked. That is not a nicety — analysis runs on
        every commit, and a merge that churned rows would bump `updated_at` on pages
        nobody touched and make the staleness work in S5 meaningless.

        An empty proposal is a no-op rather than a mass orphaning: a failed planning
        call must not retire a site that is already written.
        """
        sections = (site_map or {}).get("sections") or []
        title = str((site_map or {}).get("title") or "").strip() or "Documentation"
        site = await self.sites.get_or_create(project_id, title=title)
        counts = MergeCounts()
        if not sections:
            return counts
        if site.title != title:
            site.title = title

        existing = {
            (p.section_slug, p.slug): p for p in await self.pages.list_for_site(site.id)
        }
        proposed: set[tuple[str, str]] = set()

        for section in sections:
            section_slug = section.get("slug")
            if not section_slug:
                continue
            counts.sections += 1
            for page in section.get("pages") or []:
                slug = page.get("slug")
                if not slug:
                    continue
                key = (section_slug, slug)
                proposed.add(key)
                if (row := existing.get(key)) is not None:
                    self._update_page(row, page, counts)
                else:
                    await self._insert_page(site.id, section_slug, page, counts)

        # Anything the proposal dropped. Pinned pages are the user's, not analysis's.
        stale = [
            p
            for key, p in existing.items()
            if key not in proposed
            and not p.pinned
            and p.status != PageStatus.ORPHANED
        ]
        if stale:
            await self.pages.mark_orphaned([p.id for p in stale])
            counts.orphaned = len(stale)
            counts.orphaned_slugs = [f"{p.section_slug}/{p.slug}" for p in stale]

        await self._rebuild_nav(site, sections, kb_id=kb_id)
        await self.db.flush()

        counts.site_id = site.id
        counts.total_pages = sum((await self.pages.status_breakdown(site.id)).values())
        return counts

    async def _insert_page(
        self, site_id: int, section_slug: str, page: dict, counts: MergeCounts
    ) -> None:
        await self.pages.create(
            site_id=site_id,
            section_slug=section_slug,
            slug=page["slug"],
            title=page.get("title") or page["slug"],
            doc_type=page.get("doc_type") or "modules",
            intent=page.get("intent") or None,
            status=PageStatus.PLANNED,
            order_index=int(page.get("order_index") or 0),
            key_files_json=list(page.get("key_files") or []),
            confidence=page.get("confidence"),
            reason=page.get("reason") or None,
        )
        counts.inserted += 1
        counts.inserted_slugs.append(f"{section_slug}/{page['slug']}")

    @staticmethod
    def _update_page(row: DocPage, page: dict, counts: MergeCounts) -> None:
        """
        Refresh a page that is still proposed, without disturbing its identity.

        Dirty-checked field by field so that a re-analysis producing an identical
        proposal writes nothing at all.
        """
        incoming: dict[str, Any] = {
            "doc_type": page.get("doc_type") or row.doc_type,
            "intent": page.get("intent") or None,
            "key_files_json": list(page.get("key_files") or []),
            "confidence": page.get("confidence"),
            "reason": page.get("reason") or None,
        }
        if not row.pinned:
            incoming["title"] = page.get("title") or row.title
            incoming["order_index"] = int(page.get("order_index") or 0)

        changed = False
        for column in (*_MERGEABLE, *_MERGEABLE_UNPINNED):
            if column in incoming and getattr(row, column) != incoming[column]:
                setattr(row, column, incoming[column])
                changed = True

        # A page that fell out of a proposal and came back is live again. It keeps its
        # prose, so it returns to `ready` rather than to `planned` — orphaning was
        # always about the nav, never about the content.
        if row.status == PageStatus.ORPHANED:
            row.status = (
                PageStatus.READY if row.content_markdown else PageStatus.PLANNED
            )
            counts.restored += 1
            changed = True

        if changed:
            counts.updated += 1

    async def _rebuild_nav(
        self, site: DocSite, sections: list[dict], *, kb_id: int | None
    ) -> None:
        """
        Rewrite the ordered nav from the proposal, keeping what the user pinned.

        Sections holding surviving unproposed pages are appended rather than dropped:
        a pinned page whose section left the proposal must still be reachable, and a
        nav entry that opens onto nothing is worse than one out of the model's order.
        """
        pinned_titles = {
            entry.get("slug"): entry
            for entry in site.nav_json or []
            if isinstance(entry, dict) and entry.get("pinned")
        }

        nav: list[dict] = []
        seen: set[str] = set()
        for index, section in enumerate(sections):
            slug = section.get("slug")
            if not slug or slug in seen:
                continue
            seen.add(slug)
            kept = pinned_titles.get(slug)
            nav.append(
                {
                    "slug": slug,
                    "title": (kept or section).get("title") or slug,
                    "order_index": index,
                    "pinned": bool(kept),
                }
            )

        live = await self.pages.list_for_site(
            site.id,
            statuses=[s for s in PageStatus if s != PageStatus.ORPHANED],
        )
        for page in live:
            if page.section_slug in seen:
                continue
            seen.add(page.section_slug)
            kept = pinned_titles.get(page.section_slug)
            nav.append(
                {
                    "slug": page.section_slug,
                    "title": (kept or {}).get("title")
                    or page.section_slug.replace("-", " ").title(),
                    "order_index": len(nav),
                    "pinned": bool(kept),
                }
            )

        if site.nav_json != nav:
            site.nav_json = nav
        if kb_id is not None and site.kb_id != kb_id:
            site.kb_id = kb_id

    # ── Scope: which pages one composition job writes ─────────────────────────

    async def resolve_scope(
        self, project_id: int, requested: Sequence[str], *, max_pages: int | None = None
    ) -> list[DocPage]:
        """
        Turn what the user asked for into the pages a job will write.

        Two address forms, because both are natural things to ask for:

            "api/endpoints"   one page
            "api"             every page of that section worth writing

        Naming a page explicitly always honours it. Naming a *section* applies the
        evidence gate: pages the planner could not anchor on a single real file are
        skipped, for the same reason narrative topics are gated — a page written
        from no evidence is worse than a page that says "not yet written".

        Raises `ValidationError` when the scope is empty or over the per-job cap,
        rather than starting an hour-long job the user did not intend.
        """
        site = await self.sites.get_with_pages(project_id)
        if site is None:
            raise NotFoundError("Documentation site for project", project_id)

        by_address = {(p.section_slug, p.slug): p for p in site.pages}
        by_section: dict[str, list[DocPage]] = {}
        for page in sorted(site.pages, key=lambda p: (p.order_index, p.id)):
            by_section.setdefault(page.section_slug, []).append(page)

        selected: list[DocPage] = []
        unknown: list[str] = []
        for address in requested:
            section, _, slug = str(address).strip().partition("/")
            if slug:
                if (page := by_address.get((section, slug))) is not None:
                    selected.append(page)
                else:
                    unknown.append(address)
            elif section in by_section:
                selected.extend(p for p in by_section[section] if self._worth_writing(p))
            else:
                unknown.append(address)

        if unknown:
            raise ValidationError(
                "No page in this site matches: " + ", ".join(sorted(set(unknown)))
            )

        # Dedupe while keeping the order asked for — "api" then "api/overview" must
        # not write the overview twice.
        deduped = list(dict.fromkeys(selected))
        if not deduped:
            raise ValidationError(
                "Nothing to write: every page in this scope is already written or "
                "has no evidence behind it."
            )
        if max_pages and len(deduped) > max_pages:
            raise ValidationError(
                f"{len(deduped)} pages requested but the per-job limit is {max_pages}. "
                "Compose a section at a time."
            )
        return deduped

    @staticmethod
    def _worth_writing(page: DocPage) -> bool:
        """
        What "write this section" means, as opposed to "write this page".

        Three exclusions, each for its own reason:

          * **already written** — asking for a section is asking for the gaps in it.
            Re-running a page that is already `ready` costs a quality call per
            heading to produce roughly what is already there. Naming the page
            explicitly is how you regenerate one.
          * **no anchor files** — a page with nothing to retrieve gets written from
            the narratives alone, which is how generated documentation starts
            sounding like it could be about any codebase. Same evidence gate the
            narrative topics get.
          * **orphaned** — off the live nav. An explicit address still reaches it.
        """
        if page.status in (PageStatus.ORPHANED, PageStatus.READY, PageStatus.GENERATING):
            return False
        return bool(page.key_files_json)

    # ── Staleness ─────────────────────────────────────────────────────────────

    async def mark_stale(self, project_id: int, kb) -> dict[str, list[str]]:
        """
        Mark exactly the pages a new build invalidated.

        A written page records the files it was written from and the knowledge base
        it was written against. Comparing that build's digest for each of those files
        with this build's says precisely whether the page is out of date — a file
        whose digest changed, or that has gone entirely.

        The precision is the whole point. *"4 pages are out of date"* with a
        one-click refresh of exactly those is a different product from "your docs
        might be old"; the latter is what every documentation generator already
        offers, and nobody acts on it.

        Pages written against *this* build are left alone, and so is anything that
        is not `ready` — a `planned` page cannot be stale, and re-marking a `stale`
        one changes nothing.
        """
        site = await self.sites.get_with_pages(project_id)
        if site is None:
            return {"stale": [], "unchanged": []}

        current: dict[str, str] = kb.file_hashes_json or {}
        # Without digests there is nothing to compare against — an older build, or
        # one whose extraction failed. Saying nothing beats marking the whole site
        # stale on the strength of a missing column.
        if not current:
            return {"stale": [], "unchanged": []}

        stale: list[str] = []
        unchanged: list[str] = []
        previous_hashes: dict[int, dict[str, str]] = {}
        repos = KnowledgeRepositories.for_session(self.db)

        for page in site.pages:
            if page.status != PageStatus.READY or page.kb_id in (None, kb.id):
                continue
            sources = list(page.source_files_json or [])
            if not sources:
                continue

            if page.kb_id not in previous_hashes:
                previous = await repos.bases.get_by_id(page.kb_id)
                previous_hashes[page.kb_id] = (previous.file_hashes_json or {}) if previous else {}
            before = previous_hashes[page.kb_id]
            if not before:
                continue

            if any(current.get(path) != before.get(path) for path in sources):
                page.status = PageStatus.STALE
                stale.append(f"{page.section_slug}/{page.slug}")
            else:
                unchanged.append(f"{page.section_slug}/{page.slug}")

        await self.db.flush()
        return {"stale": stale, "unchanged": unchanged}

    async def describe_scope(
        self, project_id: int, pages: Sequence[DocPage]
    ) -> dict:
        """
        What a job is about to do, in the reader's vocabulary rather than the
        pipeline's.

        Recorded on the job so its row can say *"wrote API Reference (3 pages)"*
        instead of "composition completed" — and say it while the job is still
        queued, which a join through `doc_pages.job_id` cannot.
        """
        site = await self.sites.get_for_project(project_id)
        titles = {
            entry.get("slug"): entry.get("title")
            for entry in (site.nav_json if site else []) or []
            if isinstance(entry, dict)
        }
        sections: list[str] = []
        for page in pages:
            if page.section_slug not in sections:
                sections.append(page.section_slug)
        return {
            "kind": "pages",
            "sections": sections,
            "pages": [f"{p.section_slug}/{p.slug}" for p in pages],
            #: Pre-rendered so the UI never has to fetch the site to label a job.
            "labels": [titles.get(s) or s.replace("-", " ").title() for s in sections],
        }

    async def mark_generating(self, page_ids: Sequence[int], job_id: int) -> None:
        """Claim the pages a job is about to write, so the nav can show them working."""
        if not page_ids:
            return
        await self.db.execute(
            update(DocPage)
            .where(DocPage.id.in_(list(page_ids)))
            .values(status=PageStatus.GENERATING, job_id=job_id),
            execution_options={"synchronize_session": "fetch"},
        )
        await self.db.flush()

    async def publish_page(
        self,
        page_id: int,
        *,
        content_markdown: str,
        job_id: int,
        kb_id: int | None,
        commit_sha: str | None,
        source_files: Sequence[str],
        qa: dict | None = None,
        grounding: dict | None = None,
    ) -> DocPage | None:
        """
        Record one written page and everything it was written from.

        The provenance is the point. "Written from these 12 files at commit 4065c2f"
        is what makes generated documentation auditable, and it is what lets a new
        commit mark exactly the pages its changes invalidated rather than the whole
        site.

        A rewrite keeps the previous prose. Reviewing a regenerated page as a diff
        against what it used to say is a different activity from reading a fresh
        blob and hoping — it is what makes this a review workflow rather than a
        generator.
        """
        page = await self.pages.get_by_id(page_id)
        if page is None:
            return None
        if page.content_markdown and page.content_markdown != content_markdown:
            page.previous_markdown = page.content_markdown
        page.content_markdown = content_markdown
        page.word_count = len(content_markdown.split())
        page.status = PageStatus.READY
        page.job_id = job_id
        page.kb_id = kb_id
        page.commit_sha = commit_sha
        page.source_files_json = list(dict.fromkeys(source_files))
        if qa is not None:
            page.qa_score = qa.get("score")
            page.qa_json = qa
        if grounding is not None:
            # Stored with the page, not recomputed on read: it describes *this*
            # generation, and the same markdown checked against a later knowledge
            # base would score differently.
            page.grounding_json = grounding
        await self.db.flush()
        return page

    async def fail_page(self, page_id: int, job_id: int) -> None:
        """
        A page whose generation produced nothing.

        Marked `failed` rather than left `generating`, which would strand it in a
        spinner forever, and rather than reverted to `planned`, which would hide
        that anything went wrong.
        """
        page = await self.pages.get_by_id(page_id)
        if page is None:
            return
        # A page that already had prose keeps it: a failed rewrite is not a reason to
        # take a working page off the site.
        page.status = PageStatus.READY if page.content_markdown else PageStatus.FAILED
        page.job_id = job_id
        await self.db.flush()

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get_site(
        self, project_id: int, user: User, version_label: str | None = None
    ) -> SiteOut | None:
        """
        The map with per-page status, in nav order.

        Returns None when a project has never been analysed — the same signal
        `get_summary` uses, so the UI offers analysis rather than an empty site.

        A version label reads a frozen snapshot instead of the live site. The code
        below is unchanged either way: a version's pages are ordinary rows, which is
        the whole reason versions were built this way.
        """
        await self.projects.get(project_id, user)

        site = await self.sites.get_for_project(project_id)
        if site is None:
            return None

        version = await self._resolve_version(site, version_label)
        pages = await self.pages.list_for_site(
            site.id, version_id=version.id if version else None, limit=1000
        )
        nav = (version.nav_json if version else site.nav_json) or []
        versions = await self.versions.list_for_site(site.id)

        by_section: dict[str, list[DocPage]] = {}
        orphans: list[DocPage] = []
        counts: dict[str, int] = {}
        for page in sorted(pages, key=lambda p: (p.order_index, p.id)):
            counts[page.status] = counts.get(page.status, 0) + 1
            if page.status == PageStatus.ORPHANED:
                orphans.append(page)
            else:
                by_section.setdefault(page.section_slug, []).append(page)

        sections = [
            SiteSectionOut(
                slug=entry.get("slug", ""),
                title=entry.get("title") or entry.get("slug", ""),
                order_index=int(entry.get("order_index") or index),
                pinned=bool(entry.get("pinned")),
                pages=[
                    SitePageOut.model_validate(p)
                    for p in by_section.get(entry.get("slug", ""), [])
                ],
            )
            for index, entry in enumerate(nav)
            if isinstance(entry, dict)
        ]

        return SiteOut(
            id=site.id,
            project_id=site.project_id,
            title=site.title,
            kb_id=site.kb_id,
            sections=sections,
            orphaned_pages=[SitePageOut.model_validate(p) for p in orphans],
            page_counts=counts,
            home_markdown=await self._home(site),
            version=version.label if version else None,
            versions=[SiteVersionOut.model_validate(v) for v in versions],
            updated_at=site.updated_at,
        )

    async def _home(self, site: DocSite) -> str | None:
        """
        The landing page, derived from the map every time it is read.

        Home is the one page whose content depends on the *whole* nav, so it has to
        change whenever the nav does. Generating it at read time is the only version
        of that which cannot go stale — and it costs nothing, because everything it
        needs already exists: the overview narrative analysis wrote once, and the
        section titles and page intents the site planner produced.

        (This answers open question 3 — templated from the map, not written by a
        model. A model call here would be paid on every nav change to restate facts
        we already hold in structured form.)
        """
        if site.kb_id is None:
            return None
        narrative = await KnowledgeRepositories.for_session(self.db).narratives.get(
            site.kb_id, NarrativeTopic.OVERVIEW
        )
        return narrative.content_md if narrative else None

    # ── Versions ──────────────────────────────────────────────────────────────

    async def list_versions(self, project_id: int, user: User) -> list[SiteVersionOut]:
        await self.projects.get(project_id, user)
        site = await self.sites.get_for_project(project_id)
        if site is None:
            return []
        return [
            SiteVersionOut.model_validate(v)
            for v in await self.versions.list_for_site(site.id)
        ]

    async def create_version(
        self, project_id: int, label: str, user: User, notes: str | None = None
    ) -> SiteVersionOut:
        """
        Freeze the site as it stands.

        The snapshot copies pages rather than referencing them, because the live
        pages keep changing — that is the entire point of the live set — and a
        version that quietly followed them would not be a version.

        Only pages with prose are copied. A snapshot of what a project *planned* to
        document at some past moment is not a thing anyone wants to read.
        """
        await self.projects.get(project_id, user)

        site = await self.sites.get_with_pages(project_id)
        if site is None:
            raise NotFoundError("Documentation site for project", project_id)

        label = label.strip()
        if not label:
            raise ValidationError("A version needs a label.")
        if await self.versions.get_by_label(site.id, label) is not None:
            raise ValidationError(f"This site already has a version called {label!r}.")

        written = [
            p
            for p in site.pages
            if p.content_markdown and p.status != PageStatus.ORPHANED
        ]
        if not written:
            raise ValidationError("There is nothing written to snapshot yet.")

        shas = {p.commit_sha for p in written if p.commit_sha}
        version = await self.versions.create(
            site_id=site.id,
            label=label,
            notes=notes,
            # One commit only when the whole snapshot came from one — otherwise a
            # single sha would be a lie about where the prose came from.
            commit_sha=shas.pop() if len(shas) == 1 else None,
            nav_json=list(site.nav_json or []),
            page_count=len(written),
            created_by=user.id,
            snapshot_at=datetime.now(UTC),
        )

        for page in written:
            self.db.add(
                DocPage(
                    site_id=site.id,
                    version_id=version.id,
                    section_slug=page.section_slug,
                    slug=page.slug,
                    title=page.title,
                    doc_type=page.doc_type,
                    intent=page.intent,
                    # Frozen: a snapshot is never stale, never regenerated, never
                    # planned. Whatever the live page becomes, this stays readable.
                    status=PageStatus.READY,
                    order_index=page.order_index,
                    pinned=page.pinned,
                    content_markdown=page.content_markdown,
                    word_count=page.word_count,
                    job_id=page.job_id,
                    kb_id=page.kb_id,
                    commit_sha=page.commit_sha,
                    source_files_json=list(page.source_files_json or []),
                    key_files_json=list(page.key_files_json or []),
                    confidence=page.confidence,
                    reason=page.reason,
                    qa_score=page.qa_score,
                    qa_json=dict(page.qa_json or {}),
                )
            )
        await self.db.commit()
        return SiteVersionOut.model_validate(version)

    async def _resolve_version(self, site: DocSite, label: str | None):
        """A version by label, or None for the live site."""
        if not label:
            return None
        version = await self.versions.get_by_label(site.id, label)
        if version is None:
            raise NotFoundError("Site version", label)
        return version

    # ── Export ────────────────────────────────────────────────────────────────

    async def export_tree(
        self, project_id: int, user: User, version_label: str | None = None
    ) -> SiteTree:
        """
        The site as an export target sees it — a neutral tree, no ORM.

        Works the same for the live site and for a frozen version, because a
        version's pages are ordinary rows: only the filter changes.
        """
        await self.projects.get(project_id, user)

        site = await self.sites.get_for_project(project_id)
        if site is None:
            raise NotFoundError("Documentation site for project", project_id)

        version = await self._resolve_version(site, version_label)
        pages = await self.pages.list_for_site(
            site.id, version_id=version.id if version else None
        )
        nav = (version.nav_json if version else site.nav_json) or []

        by_section: dict[str, list[ExportPage]] = {}
        for page in sorted(pages, key=lambda p: (p.order_index, p.id)):
            if page.status == PageStatus.ORPHANED or not page.content_markdown:
                continue
            by_section.setdefault(page.section_slug, []).append(
                ExportPage(
                    section_slug=page.section_slug,
                    slug=page.slug,
                    title=page.title,
                    content_markdown=page.content_markdown,
                    order_index=page.order_index,
                    intent=page.intent,
                    commit_sha=page.commit_sha,
                    source_files=list(page.source_files_json or []),
                )
            )

        sections = [
            ExportSection(
                slug=entry.get("slug", ""),
                title=entry.get("title") or entry.get("slug", ""),
                pages=by_section.get(entry.get("slug", ""), []),
            )
            for entry in nav
            if isinstance(entry, dict)
        ]
        return SiteTree(
            title=site.title,
            sections=sections,
            home_markdown=await self._home(site),
            version_label=version.label if version else None,
        )

    async def export(
        self, project_id: int, fmt: str, user: User, version_label: str | None = None
    ) -> tuple[bytes, str, str]:
        """
        The site as a downloadable archive: `(bytes, filename, media_type)`.

        Built in memory and streamed straight back rather than uploaded to S3 like
        the legacy document exports. An export is a snapshot of what the user is
        looking at right now; storing it would immediately be a stale copy of a
        thing that regenerates itself.
        """
        tree = await self.export_tree(project_id, user, version_label)
        if tree.is_empty:
            raise ValidationError("There is nothing written to export yet.")

        stem = slugify_filename(tree.title.lower().replace(" ", "-")) or "site"
        if tree.version_label:
            stem = f"{stem}-{slugify_filename(tree.version_label)}"

        if fmt == "mkdocs":
            from app.formatters.mkdocs import MkDocsFormatter

            return MkDocsFormatter().format_site_tree(tree), f"{stem}-mkdocs.zip", "application/zip"
        if fmt == "docusaurus":
            from app.formatters.docusaurus import DocusaurusFormatter

            return (
                DocusaurusFormatter().format_site_tree(tree),
                f"{stem}-docusaurus.zip",
                "application/zip",
            )
        if fmt == "html":
            from app.formatters.static_site import StaticSiteFormatter

            return (
                StaticSiteFormatter().format_site_tree(tree),
                f"{stem}-html.zip",
                "application/zip",
            )
        if fmt == "markdown":
            return self._markdown_zip(tree), f"{stem}-markdown.zip", "application/zip"

        raise ValidationError(f"Unknown export format {fmt!r}.")

    @staticmethod
    def _markdown_zip(tree: SiteTree) -> bytes:
        """
        The page tree as plain files — the escape hatch.

        Every other target imposes a generator's conventions. This is the site as it
        is stored, so a team can put it anywhere without adopting anything.
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for section in tree.sections:
                for page in section.pages:
                    zf.writestr(
                        f"{slugify_filename(section.slug)}/{slugify_filename(page.slug)}.md",
                        f"# {page.title}\n\n"
                        + rewrite_links(page.content_markdown, from_page=page.address),
                    )
            if tree.home_markdown:
                zf.writestr("index.md", f"# {tree.title}\n\n{tree.home_markdown}\n")
        return buf.getvalue()

    async def get_page(
        self,
        project_id: int,
        section_slug: str,
        slug: str,
        user: User,
        version_label: str | None = None,
    ) -> SitePageDetail:
        """
        One page with its prose.

        Separate from `get_site` because the map is fetched on every nav render and
        a thirty-page site's markdown is megabytes. A `planned` page resolves too —
        it has no content, and the reader shows what it *will* cover instead.
        """
        await self.projects.get(project_id, user)

        site = await self.sites.get_for_project(project_id)
        if site is None:
            raise NotFoundError("Documentation site for project", project_id)

        version = await self._resolve_version(site, version_label)
        page = await self.pages.get_by_slug(
            site.id, section_slug, slug, version_id=version.id if version else None
        )
        if page is None:
            raise NotFoundError("Page", f"{section_slug}/{slug}")

        detail = SitePageDetail.model_validate(page)
        detail.section_title = next(
            (
                entry.get("title")
                for entry in ((version.nav_json if version else site.nav_json) or [])
                if isinstance(entry, dict) and entry.get("slug") == section_slug
            ),
            section_slug,
        )
        return detail

    async def delete_page(self, project_id: int, section_slug: str, slug: str, user: User) -> None:
        """
        Remove a page from the live site, at the user's explicit request.

        This is the one place a page is deleted, and it is deliberately not what
        re-analysis does. When the *model* stops proposing a page it becomes
        `orphaned` — the slug is a URL somebody may have bookmarked, and analysis
        changing its mind is not a reason to break it. A person choosing to remove a
        page is a different act, and they get a real delete.

        Only the live page goes. Frozen versions keep their copy: a snapshot is a
        record of what the site said at a moment, and editing it after the fact would
        make it worthless as one.

        A page being written right now is refused rather than deleted. The job would
        finish and write its prose back to a row that no longer exists, which fails
        deep inside the publisher for reasons nobody could reconstruct from the error.
        """
        await self.projects.get(project_id, user)

        site = await self.sites.get_for_project(project_id)
        if site is None:
            raise NotFoundError("Documentation site for project", project_id)

        page = await self.pages.get_by_slug(site.id, section_slug, slug, version_id=None)
        if page is None:
            raise NotFoundError("Page", f"{section_slug}/{slug}")

        if page.status == PageStatus.GENERATING:
            raise ValidationError(
                f"'{section_slug}/{slug}' is being written right now. "
                "Wait for the run to finish, or cancel it, then delete the page."
            )

        await self.pages.delete(page.id)
        logger.info(
            "doc_page_deleted",
            project_id=project_id,
            site_id=site.id,
            address=f"{section_slug}/{slug}",
            status=str(page.status),
            user_id=user.id,
        )


__all__ = ["SiteService", "MergeCounts"]
