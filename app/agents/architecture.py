import json
from typing import Any

from app.agents.base import BaseAgent
from app.llm.prompts.architecture_prompts import ARCHITECTURE_ANALYSIS


class ArchitectureAgent(BaseAgent):
    name = "architecture_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        await self._emit_log("info", "ArchitectureAgent: building architecture map")
        await self._update_step(self.name, "running")

        project = state["project"]
        codebase = state.get("codebase")

        file_listing = self._build_file_listing(codebase)
        symbols_summary = self._build_symbols_summary(codebase)
        languages = (
            ", ".join(f"{lang} ({n})" for lang, n in codebase.languages.items())
            if codebase else "unknown"
        )
        file_count = str(codebase.total_files) if codebase else "0"

        messages = ARCHITECTURE_ANALYSIS.render(
            project_name=project.name,
            languages=languages,
            file_count=file_count,
            file_listing=file_listing,
            symbols_summary=symbols_summary,
        )

        try:
            raw = await self._call_llm(messages, task_type="architecture")
            architecture_map = json.loads(self._extract_json(raw))
        except Exception as exc:
            await self._emit_log("warning", f"Architecture LLM parse failed: {exc} — using fallback")
            architecture_map = self._fallback_map(codebase, project.name)

        await self._update_step(self.name, "completed", {
            "services": len(architecture_map.get("services", [])),
        })
        await self._emit_log("info", "Architecture map built",
                             services=len(architecture_map.get("services", [])))

        return {**state, "architecture_map": architecture_map}

    def _build_file_listing(self, codebase) -> str:
        if not codebase:
            return "(no files)"
        lines = [f"  {f.path} ({f.language})" for f in codebase.files[:60]]
        if codebase.total_files > 60:
            lines.append(f"  ... and {codebase.total_files - 60} more")
        return "\n".join(lines)

    def _build_symbols_summary(self, codebase) -> str:
        if not codebase:
            return ""
        lines = []
        for f in codebase.files[:15]:
            if f.symbols:
                names = ", ".join(s["name"] for s in f.symbols[:6])
                lines.append(f"  {f.path}: {names}")
        return "\n".join(lines)

    def _extract_json(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        if "```" in raw:
            raw = raw.split("```")[0]
        return raw.strip()

    def _fallback_map(self, codebase, project_name: str) -> dict:
        lang = codebase.primary_language if codebase else "unknown"
        return {
            "services": [{"name": project_name, "type": "application", "description": "", "files": []}],
            "tech_stack": {"language": lang or "unknown", "frameworks": [], "databases": [], "infra": []},
            "patterns": [],
            "entry_points": [],
            "external_dependencies": [],
        }
