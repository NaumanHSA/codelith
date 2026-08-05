import json
from typing import Any

from app.agents.base import BaseAgent
from app.llm.prompts.planner_prompts import DOCUMENTATION_PLAN


class PlannerAgent(BaseAgent):
    name = "planner_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="PlannerAgent: generating section-level documentation plan",
            end_message="PlannerAgent: complete",
        ) as t:
            await self._emit_log("info", "Planner analyzing architecture and files")
            await self._update_step(self.name, "running")

            project = state["project"]
            codebase = state.get("codebase")
            doc_types = state.get("doc_types", ["architecture"])
            architecture_map: dict = state.get("architecture_map", {})

            messages = DOCUMENTATION_PLAN.render(
                project_name=project.name,
                languages=", ".join(codebase.languages.keys()) if codebase else "unknown",
                file_count=str(codebase.total_files) if codebase else "0",
                doc_types=", ".join(doc_types),
                architecture_json=json.dumps(architecture_map, indent=2)[:3000],
                file_listing=self._file_listing(codebase),
            )

            plan = await self._call_llm_json(messages, task_type="plan") or {
                "documents": self._default_plan(doc_types),
            }

            t.outputs(plan_docs=len(plan.get("documents", [])))
            await self._update_step(self.name, "completed", {"plan": plan})
            await self._emit_log("info", "Plan generated", plan_docs=len(plan.get("documents", [])))

            return {"documentation_plan": plan}

    def _file_listing(self, codebase) -> str:
        if not codebase:
            return "(no files)"
        lines = [f"  {f.path}" for f in codebase.files[:40]]
        if codebase.total_files > 40:
            lines.append(f"  ... and {codebase.total_files - 40} more")
        return "\n".join(lines)

    def _default_plan(self, doc_types: list[str]) -> list[dict]:
        defaults = {
            "architecture": ["Overview", "Components", "Data Flow", "Configuration", "Deployment"],
            "api": ["Overview", "Authentication", "Endpoints", "Request & Response Schemas", "Error Handling"],
            "module": ["Purpose", "Public API", "Usage Examples", "Dependencies"],
            "tutorial": ["Introduction", "Prerequisites", "Step-by-Step Guide", "Troubleshooting"],
            "runbook": ["Overview", "Prerequisites", "Procedures", "Rollback", "Monitoring"],
        }
        return [
            {
                "type": dt,
                "title": dt.title(),
                "sections": [{"name": s, "focus": s, "key_files": []} for s in defaults.get(dt, ["Overview"])],
            }
            for dt in doc_types
        ]
