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
            start_message="PlannerAgent: generating documentation plan",
            end_message="PlannerAgent: complete",
        ) as t:
            await self._emit_log("info", "Planner analyzing project")
            await self._update_step(self.name, "running")

            project = state["project"]
            codebase = state.get("codebase")
            doc_types = state.get("doc_types", ["architecture"])

            messages = DOCUMENTATION_PLAN.render(
                project_name=project.name,
                languages=", ".join(codebase.languages.keys()) if codebase else "unknown",
                file_count=str(codebase.total_files) if codebase else "0",
                doc_types=", ".join(doc_types),
            )

            plan = await self._call_llm_json(messages, task_type="plan") or {
                "documents": [],
                "strategy_notes": "Plan generation failed — using defaults",
            }

            t.outputs(plan_docs=len(plan.get("documents", [])))
            await self._update_step(self.name, "completed", {"plan": plan})
            await self._emit_log("info", "Plan generated", plan_docs=len(plan.get("documents", [])))

            return {**state, "documentation_plan": plan}
