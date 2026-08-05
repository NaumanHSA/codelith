import json
from typing import Any

from app.agents.base import BaseAgent
from app.llm.prompts.diagram_prompts import ARCHITECTURE_DIAGRAM, SEQUENCE_DIAGRAM
from app.tracing.artifacts import save_text_artifact


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

            strategy: dict = state.get("strategy", {})
            if not strategy.get("generate_diagrams", True):
                await self._emit_log("info", "DiagramAgent: skipped (strategy: no diagrams needed)")
                t.outputs(diagrams=0, skipped=True)
                await self._update_step(self.name, "completed", {"diagrams": 0, "skipped": True})
                return {"diagrams": []}

            project = state["project"]
            architecture_map: dict = state.get("architecture_map", {})
            sandbox = state.get("sandbox")
            generated_docs: list[dict] = state.get("generated_docs", [])

            services_list = self._services_list(architecture_map)
            entry_points = ", ".join(architecture_map.get("entry_points", [])) or "main"
            patterns = ", ".join(architecture_map.get("patterns", [])) or "none identified"
            external_deps = ", ".join(architecture_map.get("external_dependencies", [])) or "none"
            # Keep prompts lean — the local model slows badly on long diagram prompts
            architecture_json = json.dumps(architecture_map, indent=2)[:1200]
            doc_context = self._extract_doc_context(generated_docs, preferred_type="architecture")[:1000]

            diagrams: list[dict] = []

            arch_diagram = await self._generate_diagram(
                ARCHITECTURE_DIAGRAM,
                project_name=project.name,
                services_list=services_list,
                architecture_json=architecture_json,
                patterns=patterns,
                external_deps=external_deps,
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
                patterns=patterns,
                doc_context=doc_context,
            )
            if seq_diagram:
                diagrams.append({
                    "name": "Request Flow",
                    "diagram_type": "sequence",
                    "content": seq_diagram,
                })

            if sandbox and diagrams:
                try:
                    diagrams_dir = sandbox.outputs / "diagrams"
                    diagrams_dir.mkdir(parents=True, exist_ok=True)
                    for d in diagrams:
                        safe_name = d["name"].lower().replace(" ", "_").replace("/", "-")
                        (diagrams_dir / f"{safe_name}.mmd").write_text(d["content"], encoding="utf-8")
                except Exception:
                    pass

            for d in diagrams:
                save_text_artifact(f"diagram.{d['name']}", d["content"], ext="mmd")

            t.outputs(diagrams=len(diagrams))
            await self._update_step(self.name, "completed", {"diagrams": len(diagrams)})
            await self._emit_log("info", "Diagrams generated", count=len(diagrams))

            return {"diagrams": diagrams}

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
        lines = []
        for s in services:
            desc = s.get("description") or s.get("type", "")
            files = s.get("files", [])
            files_hint = f" [files: {', '.join(files[:2])}]" if files else ""
            lines.append(f"- {s['name']} ({s.get('type', 'service')}): {desc}{files_hint}")
        return "\n".join(lines)

    def _extract_doc_context(self, generated_docs: list[dict], preferred_type: str = "architecture") -> str:
        for doc in generated_docs:
            if doc.get("doc_type") == preferred_type:
                content = doc.get("content_markdown", "")
                return content[:2000] if content else "(no doc content)"
        # Fallback: first available doc
        for doc in generated_docs:
            content = doc.get("content_markdown", "")
            if content:
                return content[:2000]
        return "(no generated doc content yet)"
