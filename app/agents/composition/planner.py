"""
Section planning from the knowledge base.

The previous planner was handed a raw file listing and asked to infer structure. This
one reads module summaries, roles and facts that analysis already produced, so it
plans from understanding rather than from filenames — and crucially it emits
`key_files` drawn from the real inventory, which is what makes retrieve-then-write
possible downstream.

**Page mode moves the whole thing down a level.** When the job writes site pages, the
document's structure is no longer this stage's to invent: analysis already decided
what pages exist and what each one is for, so the question becomes "what headings does
*this* page need, given its intent and its anchor files". That is a smaller,
better-defined and better-grounded job than "design a document about api" — and the
site map goes into the prompt, so a page can be told what its neighbours cover and
therefore what not to repeat.

The two modes share `_validate` and the same `key_files`-against-the-whole-KB rule.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.config import get_settings
from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.constants import EntityKind, ModuleRole, NarrativeTopic
from app.knowledge.narratives import topics_for_doc_type
from app.llm.prompts.composition_prompts import PAGE_PLAN, SECTION_PLAN
from app.tracing.artifacts import save_artifact, save_input_artifact

#: Module roles worth showing the planner, per document type.
_ROLE_FOCUS: dict[str, tuple[ModuleRole, ...]] = {
    "api": (ModuleRole.API, ModuleRole.SCHEMA, ModuleRole.SERVICE),
    "deployment": (ModuleRole.INFRA, ModuleRole.CONFIG, ModuleRole.WORKER),
    "getting_started": (ModuleRole.CONFIG, ModuleRole.CLI, ModuleRole.API),
    "modules": (ModuleRole.SERVICE, ModuleRole.UTILITY, ModuleRole.DATA_ACCESS),
}

_DEFAULT_SECTIONS: dict[str, list[str]] = {
    "architecture": ["Overview", "Components", "Data Flow", "Configuration", "Deployment"],
    "api": ["Overview", "Authentication", "Endpoints", "Schemas", "Error Handling"],
    "modules": ["Purpose", "Public API", "Usage", "Dependencies"],
    "getting_started": ["Introduction", "Prerequisites", "Installation", "First Run"],
    "deployment": ["Overview", "Prerequisites", "Configuration", "Running", "Monitoring"],
}


class CompositionPlannerAgent(BaseAgent):
    name = "composition_planner_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="Planner: planning sections from the knowledge base",
            end_message="Planner: complete",
        ) as t:
            await self._update_step(self.name, "running")

            project = state["project"]
            kb_id = state["kb_id"]
            doc_types: list[str] = state.get("doc_types") or ["architecture"]
            pages: list[dict] = state.get("pages") or []
            strategy: dict = state.get("strategy") or {}
            repos = KnowledgeRepositories.for_session(self.db)

            # The narratives this document type actually reads, at full length — the
            # planner used to see the overview alone, truncated to 1,800 chars.
            overview = await self._narratives(repos, kb_id, doc_types)
            facts = await self._facts(repos, kb_id)
            # Every file the KB knows about, tests included. `key_files` is validated
            # against this rather than against the role-filtered slice we display —
            # otherwise a correct path is discarded as a hallucination merely because
            # its module was filtered out of the prompt.
            known_files = await self._known_files(repos, kb_id)

            plans: dict[str, dict] = {}
            if pages:
                site_map: dict = state.get("site_map") or {}
                for page in pages:
                    modules = await self._modules_for(repos, kb_id, page["doc_type"])
                    plans[page["address"]] = await self._plan_page(
                        page, project, site_map, overview, modules,
                        facts, strategy, known_files,
                    )
            else:
                for doc_type in doc_types:
                    modules = await self._modules_for(repos, kb_id, doc_type)
                    plans[doc_type] = await self._plan(
                        doc_type, project, overview, modules, facts, strategy, known_files
                    )

            save_artifact("planner.documentation_plan", plans)

            total = sum(len(p.get("sections", [])) for p in plans.values())
            unit = "page" if pages else "document"
            await self._emit_log(
                "info", f"Planned {total} sections across {len(plans)} {unit}(s)"
            )
            t.outputs(doc_types=doc_types, pages=len(pages), sections=total)
            await self._update_step(
                self.name, "completed", {"sections": total, "pages": len(pages)}
            )

            return {"documentation_plan": plans}

    # ── Page mode ─────────────────────────────────────────────────────────────

    async def _plan_page(
        self, page, project, site_map, overview, modules, facts, strategy, known_files
    ) -> dict:
        """
        Headings for one page whose purpose is already fixed.

        Falls back to a single heading covering the page's own intent rather than to
        a generic outline: the page was proposed with a specific job to do, and one
        well-grounded heading is a better failure than five invented ones.
        """
        settings = get_settings()
        doc_type = page["doc_type"]
        audience, _ = self._voice(strategy, doc_type)
        anchors = [f for f in page.get("key_files") or [] if f in known_files]

        messages = PAGE_PLAN.render(
            project_name=project.name,
            page_title=page["title"],
            section_title=self._section_title(site_map, page["section_slug"]),
            doc_type=doc_type,
            intent=page.get("intent") or page["title"],
            audience=audience,
            max_headings=str(settings.SITE_MAX_HEADINGS_PER_PAGE),
            key_files="\n".join(f"  {f}" for f in anchors) or "  (none recorded)",
            site_map=self._render_site_map(site_map, exclude=page["address"]),
            overview=overview or "(none available)",
            module_inventory=self._inventory(modules),
            facts=facts,
        )

        save_input_artifact(f"planner.page.{page['slug']}.prompt", messages)

        plan = await self._call_llm_json(messages, task_type="plan")
        save_artifact(f"planner.page.{page['slug']}.raw_response", plan)

        sections = self._validate(
            plan, known_files, limit=settings.SITE_MAX_HEADINGS_PER_PAGE
        ) if plan else []
        if not sections:
            await self._emit_log(
                "warning",
                f"Planner produced no usable headings for {page['address']} — "
                "writing it as one section",
            )
            sections = [
                {
                    "name": page["title"],
                    "focus": page.get("intent") or page["title"],
                    "key_files": anchors[:5],
                }
            ]

        return {
            "type": doc_type,
            "title": page["title"],
            "page_id": page["id"],
            "address": page["address"],
            "sections": sections,
        }

    @staticmethod
    def _section_title(site_map: dict, section_slug: str) -> str:
        for section in site_map.get("sections") or []:
            if section.get("slug") == section_slug:
                return section.get("title") or section_slug
        return section_slug

    @staticmethod
    def _render_site_map(site_map: dict, *, exclude: str) -> str:
        """
        The neighbouring pages and what each is for.

        Three pages explaining the same middleware is what makes generated
        documentation feel cheap, and it cannot be fixed after the fact — each page
        has to be told, while it is being planned, what the others already own.
        """
        lines: list[str] = []
        for section in site_map.get("sections") or []:
            for page in section.get("pages") or []:
                address = f"{section.get('slug')}/{page.get('slug')}"
                if address == exclude:
                    continue
                intent = (page.get("intent") or "").strip()
                lines.append(
                    f"  {address} — {page.get('title')}" + (f": {intent}" if intent else "")
                )
        return "\n".join(lines) or "  (this is the only page)"

    @staticmethod
    def _voice(strategy: dict, doc_type: str) -> tuple[str, str]:
        for entry in strategy.get("audiences") or []:
            if entry.get("doc_type") == doc_type:
                return entry.get("audience", "developers"), entry.get("tone", "technical")
        return "developers", "technical"

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _plan(
        self, doc_type, project, overview, modules, facts, strategy, known_files: set[str]
    ) -> dict:
        audience = next(
            (
                a.get("audience", "developers")
                for a in strategy.get("audiences", [])
                if a.get("doc_type") == doc_type
            ),
            "developers",
        )
        messages = SECTION_PLAN.render(
            project_name=project.name,
            doc_type=doc_type,
            audience=audience,
            overview=overview or "(none available)",
            module_inventory=self._inventory(modules),
            facts=facts,
        )

        save_input_artifact(f"planner.{doc_type}.prompt", messages)

        plan = await self._call_llm_json(messages, task_type="plan")
        # Saved before validation so a dropped `key_files` path is visible as a diff
        # against the stored plan, not just as a missing entry.
        save_artifact(f"planner.{doc_type}.raw_response", plan)
        sections = self._validate(plan, known_files) if plan else []
        if not sections:
            await self._emit_log(
                "warning", f"Planner produced no usable sections for {doc_type} — using defaults"
            )
            sections = self._default_sections(doc_type, modules)

        return {
            "type": doc_type,
            "title": self._title(plan, project, doc_type),
            "sections": sections,
        }

    @staticmethod
    def _title(plan: dict | None, project, doc_type: str) -> str:
        """
        Fall back when the model returns a useless title.

        Observed in practice: a planner returning literally `"api"`, which becomes the
        document heading users see.
        """
        fallback = f"{project.name} — {doc_type.replace('_', ' ').title()}"
        raw = ((plan or {}).get("title") or "").strip()
        if len(raw) < 8 or raw.lower().replace(" ", "_") == doc_type.lower():
            return fallback
        return raw

    @staticmethod
    def _validate(plan: dict, known: set[str], limit: int = 8) -> list[dict]:
        """
        Keep only sections whose `key_files` exist **in the knowledge base**.

        A hallucinated path retrieves nothing and yields a section written from thin
        air, so unknown paths are dropped. `known` must be the whole KB: validating
        against the role-filtered subset shown to the planner cost run 2 two of the
        three anchor files for its opening section — both real, both dropped, leaving
        that section 15 lines of source to work from.
        """
        sections: list[dict] = []
        for raw in plan.get("sections") or []:
            name = (raw.get("name") or "").strip()
            if not name:
                continue
            sections.append(
                {
                    "name": name,
                    "focus": (raw.get("focus") or name).strip(),
                    "key_files": [f for f in (raw.get("key_files") or []) if f in known][:5],
                }
            )
        return sections[:limit]

    @staticmethod
    def _default_sections(doc_type: str, modules) -> list[dict]:
        """Fallback that still points at real files, so retrieval keeps working."""
        top_files: list[str] = []
        for module in modules[:4]:
            top_files.extend((module.files_json or [])[:2])
        names = _DEFAULT_SECTIONS.get(doc_type, ["Overview", "Usage", "Reference"])
        return [
            {"name": n, "focus": n, "key_files": top_files[:4]} for n in names
        ]

    @staticmethod
    async def _narratives(repos, kb_id: int, doc_types: list[str]) -> str:
        """Prior analysis relevant to what is being planned, full length."""
        wanted: list[NarrativeTopic] = []
        for doc_type in doc_types:
            for topic in topics_for_doc_type(doc_type):
                if topic not in wanted:
                    wanted.append(topic)

        blocks: list[str] = []
        for topic in wanted:
            if narrative := await repos.narratives.get(kb_id, topic):
                blocks.append(f"### {topic}\n{narrative.content_md}")
        return "\n\n".join(blocks)

    @staticmethod
    async def _known_files(repos, kb_id: int) -> set[str]:
        """Every file path in the KB, tests included — this is an existence check."""
        known: set[str] = set()
        for module in await repos.modules.list_by_kb(kb_id, include_tests=True, limit=1000):
            known.update(module.files_json or [])
        return known

    @staticmethod
    async def _modules_for(repos, kb_id: int, doc_type: str):
        roles = _ROLE_FOCUS.get(doc_type)
        modules = await repos.modules.list_by_kb(
            kb_id, roles=[str(r) for r in roles] if roles else None, limit=40
        )
        # A narrow role filter can come back empty on small projects; fall back to all.
        return modules or await repos.modules.list_by_kb(kb_id, limit=40)

    @staticmethod
    def _inventory(modules, limit: int = 30) -> str:
        lines = []
        for m in modules[:limit]:
            summary = (m.summary or "").strip().replace("\n", " ")
            if len(summary) > 400:
                summary = summary[:397] + "..."
            files = ", ".join((m.files_json or [])[:6])
            lines.append(f"  {m.path} — {m.role} — {summary}\n     files: {files}")
        return "\n".join(lines) or "  (no modules)"

    @staticmethod
    async def _facts(repos, kb_id: int) -> str:
        blocks: list[str] = []
        for kind in (EntityKind.ROUTE, EntityKind.ENTRYPOINT, EntityKind.DEPENDENCY):
            items = await repos.entities.list_by_kind(kb_id, kind, limit=25)
            if items:
                blocks.append(f"{kind}: " + ", ".join(i.name for i in items[:25]))
        return "\n".join(blocks) or "(none recorded)"
