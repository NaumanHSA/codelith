"""
Adding a page the model never proposed.

A reader wants something the site does not cover. This turns their sentence into a
page that the existing pipeline can write: a title, an intent, and the anchor files
retrieval says are relevant. Nothing is written — the page lands as `planned`, which
is the state analysis already produces and the studio already renders, so "Add a page"
and "a page analysis proposed" are the same thing from there on.

**Stopping at `planned` is the design, not a shortcut.** The anchor files are the
input the whole write depends on, and a bad set produces a confidently wrong page for
a quality-tier call per heading. Showing them first costs nothing and is the one
moment they can be rejected.

Two properties this must get right:

* **`pinned=True`.** The merge orphans any page the latest proposal does not contain,
  and a user's page is never in a proposal. Without the pin, the next analysis
  silently takes it off the nav.
* **A permanent slug.** It is a URL, a `[[link]]` target and the merge key, assigned
  once from the first title. `unique_slug` keeps it unique across the whole site,
  matching what `coerce_site_map` does for proposed pages.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.core.exceptions import NotFoundError, ValidationError
from app.db.repositories.knowledge import KnowledgeRepositories
from app.db.repositories.site_repo import DocPageRepository, DocSiteRepository
from app.knowledge.constants import KBStatus, NarrativeTopic, PageStatus
from app.knowledge.retrieval import SectionContextBuilder
from app.knowledge.sites import (
    KNOWN_DOC_TYPES,
    MAX_KEY_FILES,
    coerce_doc_type,
    slugify,
    unique_slug,
)
from app.llm.prompts.composition_prompts import PAGE_PROPOSAL
from app.models.user import User

logger = structlog.get_logger(__name__)

#: Chunks searched when looking for what a requested page should be written from.
#: More than the anchor list needs, because several chunks usually come from one file.
_RETRIEVAL_CANDIDATES = 24


class _Proposer(BaseAgent):
    """A `BaseAgent` purely for its LLM plumbing — retries, tracing, JSON repair.

    It runs inside a request rather than a job: deriving a title is one fast-tier call
    against a knowledge base that already exists, and making the user wait a few
    seconds beats making them poll a job to find out what their page is called.
    """

    name = "page_proposer"

    async def run(self, state):  # pragma: no cover — not a workflow node
        raise NotImplementedError

    async def propose(self, **kwargs) -> dict | None:
        return await self._call_llm_json(PAGE_PROPOSAL.render(**kwargs), task_type="extract")

    # Nothing to log against: there is no job. The base implementation would write a
    # row keyed on `self.job_id`, which does not exist here.
    async def _emit_log(self, level: str, message: str, **extra) -> None:
        logger.debug("page_proposer", level=level, message=message, **extra)

    async def _update_step(self, step_name: str, status: str, output: dict | None = None) -> None:
        return None


class PageBuilderService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.sites = DocSiteRepository(db)
        self.pages = DocPageRepository(db)

    async def propose(
        self,
        project_id: int,
        section_slug: str,
        request: str,
        user: User,
        *,
        title: str | None = None,
    ):
        """
        Create a `planned` page from a free-text request.

        `title` is optional: given one, it is used verbatim, because a reader who
        named their page meant it. Otherwise the model derives one along with the
        intent and doc type.
        """
        from app.services.project_service import ProjectService

        await ProjectService(self.db).get(project_id, user)

        if not (request or "").strip():
            raise ValidationError("Say what the page should cover.")

        site = await self.sites.get_for_project(project_id)
        if site is None:
            raise NotFoundError("Documentation site for project", project_id)

        section = next(
            (s for s in (site.nav_json or []) if s.get("slug") == section_slug), None
        )
        if section is None:
            available = ", ".join(s.get("slug", "") for s in (site.nav_json or []))
            raise ValidationError(
                f"No section '{section_slug}'. The site has: {available or '(none)'}."
            )

        repos = KnowledgeRepositories.for_session(self.db)
        kb = await repos.bases.get_latest_usable(project_id)
        if kb is None or not KBStatus(kb.status).can_serve_features:
            raise ValidationError(
                "This project has no usable knowledge base. Analyse it first — a new "
                "page is written from the same evidence as every other page."
            )

        existing = list(await self.pages.list_for_site(site.id))
        identity = await self._identity(
            project_id, section, request, title, kb, existing, repos
        )
        key_files = await self._anchor_files(project_id, kb.id, request, identity["intent"])

        # Unique across the whole site, not just the section: `coerce_site_map` uses
        # one namespace for proposed pages and the two must not disagree, or a later
        # analysis would collide with this page's slug.
        taken = {p.slug for p in existing}
        slug = unique_slug(slugify(identity["title"], fallback="page"), taken)
        order = max((p.order_index for p in existing if p.section_slug == section_slug), default=0)

        page = await self.pages.create(
            site_id=site.id,
            section_slug=section_slug,
            slug=slug,
            title=identity["title"],
            doc_type=identity["doc_type"],
            intent=identity["intent"],
            status=PageStatus.PLANNED,
            order_index=order + 1,
            # The whole reason this survives the next analysis. See the module docstring.
            pinned=True,
            key_files_json=key_files,
            confidence=None,
            reason=f"Requested by {user.email}: {request.strip()[:280]}",
        )
        await self.db.commit()

        logger.info(
            "page_added",
            project_id=project_id,
            address=f"{section_slug}/{slug}",
            key_files=len(key_files),
            user_id=user.id,
        )
        return page

    async def _identity(
        self, project_id, section, request, title, kb, existing, repos
    ) -> dict:
        """Title, intent and doc type — derived unless the reader supplied a title."""
        siblings = [p for p in existing if p.section_slug == section.get("slug")]
        overview = await repos.narratives.get(kb.id, NarrativeTopic.OVERVIEW)

        from app.db.repositories.project_repo import ProjectRepository

        project = await ProjectRepository(self.db).get_by_id(project_id)

        proposed = await _Proposer(db=self.db, job_id=0).propose(
            project_name=getattr(project, "name", "this project"),
            section_title=section.get("title") or section.get("slug"),
            request=request.strip(),
            doc_types=", ".join(sorted(KNOWN_DOC_TYPES)),
            siblings="\n".join(
                f"  {p.title} — {(p.intent or '').strip()[:120]}" for p in siblings
            )
            or "  (none yet)",
            overview=(overview.content_md[:4000] if overview else "(none available)"),
        ) or {}

        # A reader who typed a title meant it; the model only fills what is missing.
        # And a failed call must not stop the page being created — the request itself
        # is a serviceable intent, and a wrong title can be edited.
        final_title = (title or proposed.get("title") or "").strip()
        if not final_title:
            final_title = request.strip()[:80]

        intent = (proposed.get("intent") or "").strip() or request.strip()
        return {
            "title": final_title,
            "intent": intent,
            "doc_type": coerce_doc_type(proposed.get("doc_type")),
        }

    async def _anchor_files(
        self, project_id: int, kb_id: int, request: str, intent: str
    ) -> list[str]:
        """
        What the page will be written from.

        Semantic search over the same chunks composition retrieves, aimed at the
        request. Files are ranked by how many chunks each contributed, so a file the
        query matched repeatedly outranks one that matched once — which is a better
        signal for "this page is about that file" than best-single-chunk.
        """
        builder = SectionContextBuilder(
            db=self.db, kb_id=kb_id, project_id=project_id, token_budget=1
        )
        chunks = await builder._search_chunks(f"{request}\n{intent}", _RETRIEVAL_CANDIDATES)

        ranked: dict[str, int] = {}
        for chunk in chunks:
            path = getattr(chunk, "source_path", None)
            if path:
                ranked[path] = ranked.get(path, 0) + 1
        return [p for p, _ in sorted(ranked.items(), key=lambda kv: -kv[1])][:MAX_KEY_FILES]


__all__ = ["PageBuilderService"]
