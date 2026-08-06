"""
Planning the whole documentation site.

This is `suggest_doc_types()` taken one level deeper. That function proposes a menu
of *document types* with evidence and confidence; this proposes the whole **site
map** — sections, and the pages inside them — with the same grounding, so that
generating an API reference today writes into a navigation that already knows an
architecture guide will exist. Adding that guide next month slots in without
renumbering, renaming or breaking a link.

Three properties make that work, and each costs something here:

  * **Quality tier.** This is the highest-leverage call in the system: it fixes the
    shape of every document that will ever be written, and slugs are permanent. A
    bad map produces a bad site silently and forever.
  * **`key_files` validated against the whole knowledge base**, exactly as the
    composition planner does it. A hallucinated path retrieves nothing, and the page
    it anchors gets written from thin air.
  * **A deterministic fallback.** A failed call must cost site quality, not the
    site: with no map there is no nav, nothing to generate against, and the phase
    produces nothing at all.

The proposal is stored on the knowledge base (`site_map_json`) and merged into
`doc_pages` by `SiteService`, which owns every rule about what may change. Nothing
here writes a page directly — analysis proposes, the merge decides.
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.base import BaseAgent
from app.config import get_settings
from app.core.cancellation import JobCancelled
from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.roles import suggest_doc_types
from app.knowledge.sites import (
    KNOWN_DOC_TYPES,
    MAX_KEY_FILES,
    coerce_site_map,
    derive_site_map,
)
from app.llm.prompts.analysis_prompts import SITE_PLAN
from app.services.site_service import SiteService
from app.tracing.artifacts import save_artifact, save_input_artifact

#: How much of each module summary survives into a downstream prompt.
_SUMMARY_CHARS = 400
#: Modules shown to the planner. It needs breadth — a page it never sees evidence
#: for is a page nobody will ever think to write.
_INVENTORY_LIMIT = 40


class SitePlannerAgent(BaseAgent):
    name = "site_planner_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="SitePlanner: planning the documentation site",
            end_message="SitePlanner: complete",
        ) as t:
            await self._update_step(self.name, "running")

            settings = get_settings()
            project = state["project"]
            kb_id = state["kb_id"]
            repos = KnowledgeRepositories.for_session(self.db)
            sites = SiteService(self.db)

            modules = await repos.modules.list_by_kb(kb_id, include_tests=False, limit=1000)
            roles = await repos.modules.role_breakdown(kb_id)
            entity_kinds = await repos.entities.kind_breakdown(kb_id)
            topics = await repos.narratives.topics_present(kb_id)
            suggestions = suggest_doc_types(entity_kinds, roles)

            # Every file the KB knows about, tests included: `key_files` is an
            # existence check, and validating against the filtered inventory we
            # *display* would discard real paths as hallucinations.
            known_files = await self._known_files(repos, kb_id)
            existing = await sites.sites.get_with_pages(project.id)

            site_map = await self._propose(
                project=project,
                architecture_map=state.get("architecture_map") or {},
                modules=modules,
                roles=roles,
                entity_kinds=entity_kinds,
                topics=topics,
                suggestions=suggestions,
                known_files=known_files,
                existing=existing,
                settings=settings,
            )

            degraded = not site_map.get("sections")
            if degraded:
                await self._emit_log(
                    "warning", "Site planning produced no usable sections — deriving from doc types"
                )
                site_map = derive_site_map(
                    project.name,
                    suggestions,
                    key_files_by_doc_type=self._anchor_files(modules),
                    max_sections=settings.SITE_MAX_SECTIONS,
                )

            site_map["kb_id"] = kb_id
            save_artifact("site_planner.site_map", site_map)

            # The proposal is stored whether or not the merge likes it: it is what a
            # later re-merge, a diff between commits, and any debugging of a wrong
            # map are done against.
            await repos.bases.update(kb_id, site_map_json=site_map)
            counts = await sites.merge_proposal(project.id, site_map, kb_id=kb_id)

            # Then the other half of the same bookkeeping: which already-written
            # pages this commit invalidated. It runs here because this is the point
            # where the new build's file digests exist and the merged map does too.
            staleness = await sites.mark_stale(project.id, await repos.bases.get_by_id(kb_id))
            await self.db.commit()

            save_artifact(
                "site_planner.merge",
                {
                    "site_id": counts.site_id,
                    "inserted": counts.inserted,
                    "updated": counts.updated,
                    "orphaned": counts.orphaned,
                    "restored": counts.restored,
                    "inserted_slugs": counts.inserted_slugs,
                    "orphaned_slugs": counts.orphaned_slugs,
                    **staleness,
                },
            )
            await self._emit_log(
                "info",
                f"Site map: {counts.total_pages} pages across {counts.sections} sections "
                f"({counts.inserted} new, {counts.orphaned} orphaned)",
                inserted=counts.inserted,
                updated=counts.updated,
                orphaned=counts.orphaned,
                restored=counts.restored,
                degraded=degraded,
            )
            if staleness["stale"]:
                # Named, not counted: this is the message the whole staleness
                # feature exists to produce, and "4 pages are out of date" is only
                # useful if it also says which four.
                await self._emit_log(
                    "info",
                    f"{len(staleness['stale'])} page(s) are out of date at this commit",
                    pages=staleness["stale"],
                )
            t.outputs(
                sections=counts.sections,
                pages=counts.total_pages,
                stale=len(staleness["stale"]),
                degraded=degraded,
            )
            await self._update_step(
                self.name,
                "completed",
                {
                    "sections": counts.sections,
                    "pages": counts.total_pages,
                    "inserted": counts.inserted,
                    "orphaned": counts.orphaned,
                    "stale": len(staleness["stale"]),
                    "degraded": degraded,
                },
            )

            return {
                "site_map": site_map,
                "site_pages": counts.total_pages,
                "site_stale": staleness["stale"],
                "site_degraded": degraded,
            }

    # ── Proposal ──────────────────────────────────────────────────────────────

    async def _propose(
        self,
        *,
        project,
        architecture_map: dict,
        modules,
        roles: dict[str, int],
        entity_kinds: dict[str, int],
        topics: set[str],
        suggestions: list[dict],
        known_files: set[str],
        existing,
        settings,
    ) -> dict:
        """One quality-tier call, coerced onto the canonical map. Never raises."""
        messages = SITE_PLAN.render(
            project_name=project.name,
            doc_types=", ".join(sorted(KNOWN_DOC_TYPES)),
            max_sections=str(settings.SITE_MAX_SECTIONS),
            max_pages=str(settings.SITE_MAX_PAGES),
            architecture_json=json.dumps(architecture_map, indent=2)[:2500],
            roles=json.dumps(roles),
            facts=json.dumps(entity_kinds),
            suggested_doc_types=", ".join(
                f"{s['doc_type']} ({s['reason']})" for s in suggestions
            )
            or "(none)",
            topics=", ".join(sorted(topics)) or "(none)",
            module_inventory=self._inventory(modules),
            existing_map=self._existing_map(existing),
        )

        save_input_artifact("site_planner.prompt", messages)

        try:
            raw = await self._call_llm_json(messages, task_type="plan")
        except JobCancelled:
            raise
        except Exception as exc:
            await self._emit_log("warning", f"Site planning call failed: {exc}")
            return {"title": project.name, "sections": []}

        save_artifact("site_planner.raw_response", raw)
        # Coerced *after* saving the raw response, so a discarded `key_files` path or
        # a dropped section is visible as a diff rather than as an absence.
        return coerce_site_map(
            raw,
            known_files=known_files,
            fallback_title=project.name,
            max_sections=settings.SITE_MAX_SECTIONS,
            max_pages=settings.SITE_MAX_PAGES,
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    async def _known_files(repos, kb_id: int) -> set[str]:
        known: set[str] = set()
        for module in await repos.modules.list_by_kb(kb_id, include_tests=True, limit=1000):
            known.update(module.files_json or [])
        return known

    @staticmethod
    def _inventory(modules, limit: int = _INVENTORY_LIMIT) -> str:
        """
        Module path, role, summary and files.

        The files matter as much as the prose: `key_files` must be copied exactly
        from what is shown here, so anything not listed cannot survive validation.
        """
        lines = []
        for m in modules[:limit]:
            summary = (m.summary or "").strip().replace("\n", " ")
            if len(summary) > _SUMMARY_CHARS:
                summary = summary[: _SUMMARY_CHARS - 3] + "..."
            files = ", ".join((m.files_json or [])[:6])
            lines.append(f"  {m.path} — {m.role} — {summary}\n     files: {files}")
        return "\n".join(lines) or "  (no modules)"

    @staticmethod
    def _existing_map(site) -> str:
        """
        The pages that already exist, so the model reuses their slugs.

        The merge would keep an existing page whatever the model says, but a
        proposal that renames it produces a *second* page on a new slug and orphans
        the first. Showing the current map is what makes re-analysis converge.
        """
        if site is None or not site.pages:
            return "  (nothing yet — this is the first plan for this project)"
        lines = []
        for page in sorted(site.pages, key=lambda p: (p.section_slug, p.order_index)):
            lines.append(
                f"  {page.section_slug}/{page.slug} — {page.title} "
                f"[{page.doc_type}, {page.status}]"
            )
        return "\n".join(lines)

    @staticmethod
    def _anchor_files(modules) -> dict[str, list[str]]:
        """
        Real files per doc type, so even the fallback map anchors on something.

        Roles are the only signal available without an LLM, and they are the same
        signal the composition planner's `_ROLE_FOCUS` uses.
        """
        by_role: dict[str, list[str]] = {}
        for module in modules:
            by_role.setdefault(module.role, []).extend((module.files_json or [])[:2])

        def pick(*roles: str) -> list[str]:
            out: list[str] = []
            for role in roles:
                out.extend(by_role.get(role, []))
            return out[:MAX_KEY_FILES]

        return {
            "architecture": pick("service", "api", "model"),
            "api": pick("api", "schema"),
            "deployment": pick("infra", "config"),
            "getting_started": pick("config", "cli", "api"),
            "modules": pick("service", "utility", "data_access"),
            "testing": pick("test"),
        }


__all__ = ["SitePlannerAgent"]
