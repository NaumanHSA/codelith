import json
from typing import Any

from app.agents.base import BaseAgent
from app.llm.prompts.strategy_prompts import DOCUMENTATION_STRATEGY


class StrategyAgent(BaseAgent):
    name = "strategy_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="StrategyAgent: determining documentation strategy",
            end_message="StrategyAgent: complete",
        ) as t:
            await self._emit_log("info", "StrategyAgent: determining documentation strategy")
            await self._update_step(self.name, "running")

            project = state["project"]
            doc_types: list[str] = state.get("doc_types", ["architecture"])
            architecture_map: dict = state.get("architecture_map", {})
            codebase = state.get("codebase")

            messages = DOCUMENTATION_STRATEGY.render(
                project_name=project.name,
                doc_types=", ".join(doc_types),
                architecture_json=json.dumps(architecture_map, indent=2)[:3000],
                file_listing=self._file_listing(codebase),
                entry_points=", ".join(architecture_map.get("entry_points", [])) or "unknown",
                patterns=", ".join(architecture_map.get("patterns", [])) or "none identified",
            )

            strategy = await self._call_llm_json(messages, task_type="plan") or self._default_strategy(doc_types)

            t.outputs(doc_types=doc_types)
            await self._update_step(self.name, "completed", {"doc_types": doc_types})
            return {"strategy": strategy}

    def _file_listing(self, codebase) -> str:
        if not codebase:
            return "(no files)"
        lines = [f"  {f.path}" for f in codebase.files[:30]]
        if codebase.total_files > 30:
            lines.append(f"  ... and {codebase.total_files - 30} more")
        return "\n".join(lines)

    def _default_strategy(self, doc_types: list[str]) -> dict:
        return {
            "audiences": [{"doc_type": dt, "audience": "developers", "tone": "technical"} for dt in doc_types],
            "priorities": doc_types,
            "generate_diagrams": True,
            "template_hints": [
                {"doc_type": dt, "sections": ["Overview", "Usage", "API"]} for dt in doc_types
            ],
        }
