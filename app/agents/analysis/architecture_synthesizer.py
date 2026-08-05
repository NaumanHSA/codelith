"""
Architecture synthesis.

Replaces the old ReAct architecture agent, which explored the filesystem with tools
and — measured on job 18 — failed to return parseable JSON and silently fell back to
a single-shot call, leaving everything downstream working from degraded input.

There is nothing to explore here: `structured_extractor` and `module_summarizer` have
already produced the inventory. This is one grounded call over facts we hold, with a
deterministic fallback that is built from those same facts rather than guesswork.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.constants import EntityKind, ModuleRole
from app.llm.prompts.analysis_prompts import ARCHITECTURE_SYNTHESIS
from app.tracing.artifacts import save_artifact, save_input_artifact

#: How much of each module summary survives into a downstream prompt.
_SUMMARY_CHARS = 400


class ArchitectureSynthesizerAgent(BaseAgent):
    name = "architecture_synthesizer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="ArchitectureSynthesizer: building architecture map",
            end_message="ArchitectureSynthesizer: complete",
        ) as t:
            await self._update_step(self.name, "running")

            project = state["project"]
            kb_id = state["kb_id"]
            repos = KnowledgeRepositories.for_session(self.db)

            modules = await repos.modules.list_by_kb(kb_id)
            routes = await repos.entities.list_by_kind(kb_id, EntityKind.ROUTE)
            deps = await repos.entities.list_by_kind(kb_id, EntityKind.DEPENDENCY)
            entrypoints = await repos.entities.list_by_kind(kb_id, EntityKind.ENTRYPOINT)
            infra = await repos.entities.list_by_kind(kb_id, EntityKind.INFRA_RESOURCE)

            messages = ARCHITECTURE_SYNTHESIS.render(
                project_name=project.name,
                languages=", ".join(sorted({m.language for m in modules if m.language}))
                or "unknown",
                module_count=str(len(modules)),
                route_count=str(len(routes)),
                dependency_count=str(len(deps)),
                module_inventory=self._inventory(modules),
                # Cap the list we send too: the model tends to mirror its input length,
                # and a 46-name list pushed the JSON response past the model's output
                # budget, truncating it mid-array on every retry.
                dependencies=", ".join(d.name for d in deps[:30]) or "(none declared)",
                entrypoints=", ".join(e.name for e in entrypoints[:20]) or "(none detected)",
                infrastructure=", ".join(i.name for i in infra[:20]) or "(none detected)",
            )

            save_input_artifact("architecture_synthesizer.prompt", messages)

            architecture_map = await self._call_llm_json(messages, task_type="architecture")
            degraded = False
            if not architecture_map or not isinstance(architecture_map, dict):
                await self._emit_log(
                    "warning", "Architecture synthesis returned no JSON — using derived map"
                )
                architecture_map = self._derive(modules, deps, entrypoints, infra)
                degraded = True

            save_artifact("architecture_synthesizer.architecture_map", architecture_map)

            services = len(architecture_map.get("services", []) or [])
            await self._emit_log("info", "Architecture map built", services=services)
            t.outputs(services=services, degraded=degraded)
            await self._update_step(
                self.name, "completed", {"services": services, "degraded": degraded}
            )

            return {"architecture_map": architecture_map, "architecture_degraded": degraded}

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _inventory(modules, limit: int = 40) -> str:
        lines = []
        for m in modules[:limit]:
            # Summaries average ~556 chars; truncating to 240 threw away most of what
            # the summarizer was paid to produce. 400 keeps 3-4 sentences.
            summary = (m.summary or "").strip().replace("\n", " ")
            if len(summary) > _SUMMARY_CHARS:
                summary = summary[: _SUMMARY_CHARS - 3] + "..."
            lines.append(
                f"  {m.name} [{m.role}, {m.file_count} files, {m.loc} loc]"
                + (f" — {summary}" if summary else "")
            )
        return "\n".join(lines) or "  (no modules)"

    @staticmethod
    def _derive(modules, deps, entrypoints, infra) -> dict:
        """
        Fallback map assembled from extracted facts.

        Unlike the previous hardcoded stub this still reflects the real codebase, so a
        failed LLM call degrades quality rather than losing the analysis.
        """
        by_role: dict[str, list] = {}
        for m in modules:
            by_role.setdefault(m.role, []).append(m.name)

        languages = [m.language for m in modules if m.language]
        primary = max(set(languages), key=languages.count) if languages else "unknown"

        return {
            "services": [
                {
                    "name": role,
                    "type": role,
                    "description": f"{len(names)} module(s) with the {role} role",
                    "modules": names[:20],
                }
                for role, names in by_role.items()
                if role != str(ModuleRole.TEST)
            ],
            "tech_stack": {
                "language": primary,
                "frameworks": [d.name for d in deps[:15]],
                "databases": [],
                "infra": [i.name for i in infra[:10]],
            },
            "patterns": [],
            "entry_points": [e.name for e in entrypoints[:10]],
            "external_dependencies": [d.name for d in deps[:30]],
            "layers": [{"name": role, "modules": names[:20]} for role, names in by_role.items()],
        }
