"""
Entry point for Phase 2.

Resolves which knowledge base to compose from, which pages to write, and unpacks the
job config. This is where the two phases meet: everything downstream reads the KB and
never touches the repository, which no longer exists on disk by this point.

Two scopes arrive here and the rest of the graph branches on which one is set:

  * **pages** — `job_config["page_slugs"]` names pages of the project's documentation
    site. The planner plans headings inside each one, the writer fans out per page,
    and the publisher writes `doc_pages` with full provenance.
  * **doc types** — the original path, one flat document per type, kept working.

The site map is loaded in both cases when there is one: every page prompt carries it,
which is what stops three pages explaining the same middleware.
"""

from __future__ import annotations

from typing import Any

from codelith.agents.base import BaseAgent
from codelith.apps.documentation.services.site_service import SiteService
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.knowledge.constants import KBStatus
from codelith.tracing.artifacts import save_artifact


class KBLoaderAgent(BaseAgent):
    name = "kb_loader_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="KBLoader: resolving knowledge base",
            end_message="KBLoader: complete",
        ) as t:
            await self._update_step(self.name, "running")

            project = state["project"]
            job_config = state.get("job_config") or {}
            repos = KnowledgeRepositories.for_session(self.db)

            kb_id = job_config.get("kb_id")
            kb = (
                await repos.bases.get_by_id(kb_id)
                if kb_id
                else await repos.bases.get_latest_usable(project.id)
            )

            if kb is None:
                raise ValueError(
                    f"Project {project.id} has no usable knowledge base — run analysis first"
                )
            if not KBStatus(kb.status).is_usable:
                raise ValueError(f"Knowledge base {kb.id} is {kb.status}, not usable")

            stats = kb.stats_json or {}
            doc_types = job_config.get("doc_types") or ["architecture"]
            output_formats = job_config.get("output_formats") or ["markdown"]

            if kb.status == KBStatus.DEGRADED:
                await self._emit_log(
                    "warning",
                    f"Composing from a degraded knowledge base: {kb.error_message}",
                )

            sites = SiteService(self.db)
            pages = await self._load_pages(sites, project.id, job_config.get("page_slugs") or [])
            site_map = await self._load_site_map(sites, project.id)

            if pages:
                # Claimed up front so the nav can show them working. A page that is
                # still `generating` when a job dies is visible as such, which is the
                # honest state — better than silently reverting to `planned`.
                await sites.mark_generating([p["id"] for p in pages], self.job_id)
                await self.db.commit()
                await self._emit_log(
                    "info",
                    f"Writing {len(pages)} page(s) from knowledge base {kb.id}",
                    pages=[p["address"] for p in pages],
                )
            else:
                await self._emit_log(
                    "info",
                    f"Composing {doc_types} from knowledge base {kb.id}",
                    modules=stats.get("modules"),
                    narratives=stats.get("narratives"),
                )

            save_artifact(
                "kb_loader.resolved",
                {
                    "kb_id": kb.id,
                    "kb_status": kb.status,
                    "commit_sha": kb.commit_sha,
                    "architecture_map": kb.architecture_json or {},
                    "doc_types": doc_types,
                    "pages": pages,
                    "output_formats": output_formats,
                    "kb_stats": stats,
                },
            )

            t.outputs(
                kb_id=kb.id, doc_types=doc_types, pages=len(pages), kb_status=kb.status
            )
            await self._update_step(
                self.name,
                "completed",
                {"kb_id": kb.id, "doc_types": doc_types, "pages": len(pages)},
            )

            return {
                "kb_id": kb.id,
                "kb_status": kb.status,
                "kb_stats": stats,
                "commit_sha": kb.commit_sha,
                "architecture_map": kb.architecture_json or {},
                "doc_types": doc_types,
                "pages": pages,
                "site_map": site_map,
                "output_formats": output_formats,
                "requires_human_review": job_config.get("human_review", False),
                "depth": job_config.get("depth") or "standard",
                "generated_docs": [],
            }

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _load_pages(
        self, sites: SiteService, project_id: int, page_slugs: list[str]
    ) -> list[dict]:
        """
        The pages in scope, flattened onto plain dicts.

        Flattened deliberately: LangGraph state is passed between nodes that each open
        their own session, so an ORM instance loaded here would be detached by the time
        the writer touched it.
        """
        if not page_slugs:
            return []
        pages = await sites.resolve_scope(project_id, page_slugs)
        return [
            {
                "id": p.id,
                "address": f"{p.section_slug}/{p.slug}",
                "section_slug": p.section_slug,
                "slug": p.slug,
                "title": p.title,
                "doc_type": p.doc_type,
                "intent": p.intent or "",
                "key_files": list(p.key_files_json or []),
                "order_index": p.order_index,
            }
            for p in pages
        ]

    @staticmethod
    async def _load_site_map(sites: SiteService, project_id: int) -> dict:
        """
        The whole nav, not just what is in scope.

        Every page prompt carries it. Duplication across pages is harder to prevent
        than duplication within a document — a writer that cannot see that
        `api/auth` exists will explain authentication again.
        """
        site = await sites.sites.get_with_pages(project_id)
        if site is None:
            return {}
        by_section: dict[str, list[dict]] = {}
        for page in sorted(site.pages, key=lambda p: (p.order_index, p.id)):
            by_section.setdefault(page.section_slug, []).append(
                {
                    "slug": page.slug,
                    "title": page.title,
                    "intent": page.intent or "",
                    "status": page.status,
                }
            )
        return {
            "title": site.title,
            "sections": [
                {
                    "slug": entry.get("slug", ""),
                    "title": entry.get("title") or entry.get("slug", ""),
                    "pages": by_section.get(entry.get("slug", ""), []),
                }
                for entry in site.nav_json or []
                if isinstance(entry, dict)
            ],
        }
