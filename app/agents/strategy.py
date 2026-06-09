import json
from typing import Any

from app.agents.base import BaseAgent
from app.llm.prompts.strategy_prompts import DOCUMENTATION_STRATEGY


class StrategyAgent(BaseAgent):
    name = "strategy_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        await self._emit_log("info", "StrategyAgent: determining documentation strategy")
        await self._update_step(self.name, "running")

        project = state["project"]
        doc_types: list[str] = state.get("doc_types", ["architecture"])
        architecture_map: dict = state.get("architecture_map", {})

        architecture_summary = self._summarize_architecture(architecture_map)

        messages = DOCUMENTATION_STRATEGY.render(
            project_name=project.name,
            doc_types=", ".join(doc_types),
            architecture_summary=architecture_summary,
        )

        try:
            raw = await self._call_llm(messages, task_type="plan")
            strategy = json.loads(self._extract_json(raw))
        except Exception as exc:
            await self._emit_log("warning", f"Strategy LLM parse failed: {exc} — using defaults")
            strategy = self._default_strategy(doc_types)

        await self._update_step(self.name, "completed", {"doc_types": doc_types})
        return {**state, "strategy": strategy}

    def _summarize_architecture(self, arch: dict) -> str:
        if not arch:
            return "No architecture data available."
        services = arch.get("services", [])
        tech = arch.get("tech_stack", {})
        parts = []
        if services:
            parts.append("Services: " + ", ".join(s["name"] for s in services[:8]))
        if tech.get("language"):
            parts.append(f"Language: {tech['language']}")
        if tech.get("frameworks"):
            parts.append("Frameworks: " + ", ".join(tech["frameworks"][:5]))
        if arch.get("patterns"):
            parts.append("Patterns: " + ", ".join(arch["patterns"][:5]))
        return "\n".join(parts) or "Generic project."

    def _extract_json(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        if "```" in raw:
            raw = raw.split("```")[0]
        return raw.strip()

    def _default_strategy(self, doc_types: list[str]) -> dict:
        return {
            "audiences": [{"doc_type": dt, "audience": "developers", "tone": "technical"} for dt in doc_types],
            "priorities": doc_types,
            "template_hints": [{"doc_type": dt, "sections": ["Overview", "Usage", "API"]} for dt in doc_types],
        }
