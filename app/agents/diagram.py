from typing import Any

from app.agents.base import BaseAgent
from app.llm.prompts.diagram_prompts import ARCHITECTURE_DIAGRAM, SEQUENCE_DIAGRAM


class DiagramAgent(BaseAgent):
    name = "diagram_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="DiagramAgent: generating Mermaid diagrams",
            end_message="DiagramAgent: complete",
        ) as t:
            await self._emit_log("info", "DiagramAgent: generating Mermaid diagrams")
            await self._update_step(self.name, "running")

            project = state["project"]
            architecture_map: dict = state.get("architecture_map", {})

            services_list = self._services_list(architecture_map)
            tech_stack = self._tech_stack_str(architecture_map)
            entry_points = ", ".join(architecture_map.get("entry_points", [])) or "main"

            diagrams: list[dict] = []

            arch_diagram = await self._generate_diagram(
                ARCHITECTURE_DIAGRAM,
                project_name=project.name,
                services_list=services_list,
                tech_stack=tech_stack,
            )
            if arch_diagram:
                diagrams.append({
                    "name": "Architecture Overview",
                    "diagram_type": "graph",
                    "content": arch_diagram,
                })

            seq_diagram = await self._generate_diagram(
                SEQUENCE_DIAGRAM,
                project_name=project.name,
                services_list=services_list,
                entry_points=entry_points,
            )
            if seq_diagram:
                diagrams.append({
                    "name": "Request Flow",
                    "diagram_type": "sequence",
                    "content": seq_diagram,
                })

            t.outputs(diagrams=len(diagrams))
            await self._update_step(self.name, "completed", {"diagrams": len(diagrams)})
            await self._emit_log("info", "Diagrams generated", count=len(diagrams))

            return {**state, "diagrams": diagrams}

    async def _generate_diagram(self, prompt_template, **kwargs) -> str | None:
        try:
            messages = prompt_template.render(**kwargs)
            raw = await self._call_llm(messages, task_type="diagram")
            return self._clean_mermaid(raw)
        except Exception as exc:
            await self._emit_log("warning", f"Diagram generation failed: {exc}")
            return None

    def _clean_mermaid(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("mermaid"):
                raw = raw[7:]
        if "```" in raw:
            raw = raw.split("```")[0]
        return raw.strip()

    def _services_list(self, arch: dict) -> str:
        services = arch.get("services", [])
        if not services:
            return "(no services identified)"
        return "\n".join(f"- {s['name']}: {s.get('description', s.get('type', ''))}" for s in services)

    def _tech_stack_str(self, arch: dict) -> str:
        tech = arch.get("tech_stack", {})
        parts = []
        if tech.get("language"):
            parts.append(tech["language"])
        parts.extend(tech.get("frameworks", [])[:3])
        parts.extend(tech.get("databases", [])[:2])
        return ", ".join(parts) or "unknown"
