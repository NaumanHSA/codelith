from __future__ import annotations

import json
from typing import Any

from app.agents.base import BaseAgent
from app.agents.react_mixin import ReActMixin
from app.llm.prompts.architecture_prompts import ARCHITECTURE_ANALYSIS

_REACT_SYSTEM_PROMPT = """\
You are a senior software architect tasked with building a precise architecture map of a codebase.

You have access to tools to read and explore the repository. Use them to:
1. Read key configuration files (pyproject.toml, package.json, Dockerfile, docker-compose.yml, etc.)
2. Read entry-point files (main.py, index.ts, app.py, server.js, etc.)
3. Read representative source files from each major module
4. Use query_code_graph to explore import dependencies and module structure
5. Use search_codebase to find specific patterns or implementations

Once you have a clear picture, produce a JSON architecture map with this exact schema:
{
  "services": [{"name": str, "type": str, "description": str, "files": [str]}],
  "tech_stack": {"language": str, "frameworks": [str], "databases": [str], "infra": [str]},
  "patterns": [str],
  "entry_points": [str],
  "external_dependencies": [str]
}

Return ONLY the JSON — no prose, no markdown fences.
"""


class ArchitectureAgent(ReActMixin, BaseAgent):
    name = "architecture_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="ArchitectureAgent: building architecture map",
            end_message="ArchitectureAgent: complete",
        ) as t:
            await self._emit_log("info", "ArchitectureAgent: building architecture map")
            await self._update_step(self.name, "running")

            project = state["project"]
            codebase = state.get("codebase")
            repo_path = state.get("repo_path") or ""

            architecture_map = await self._build_map(project, codebase, repo_path, state)

            t.outputs(services=len(architecture_map.get("services", [])))
            await self._update_step(self.name, "completed", {
                "services": len(architecture_map.get("services", [])),
            })
            await self._emit_log("info", "Architecture map built",
                                 services=len(architecture_map.get("services", [])))

            return {**state, "architecture_map": architecture_map}

    async def _build_map(self, project, codebase, repo_path: str, state: dict) -> dict:
        # ── Try ReAct agent with MCP tools when we have a real repo path ────────
        if repo_path:
            file_listing = self._build_file_listing(codebase)
            api_context = self._format_api_context(state.get("api_specs", []))
            infra_context = self._format_infra_context(state.get("infra_context", []))

            user_message = (
                f"Analyze the project '{project.name}' located at: {repo_path}\n\n"
                f"Known file listing (from static parse):\n{file_listing}\n\n"
                + (f"API specs found:\n{api_context}\n\n" if api_context else "")
                + (f"Infrastructure context:\n{infra_context}\n\n" if infra_context else "")
                + "Use the file listing and context above as your map. "
                "Use query_code_graph to explore import dependencies. "
                "Skip directory listing — go directly to reading config files and key modules."
            )

            result = await self._run_react(
                system_prompt=_REACT_SYSTEM_PROMPT,
                user_message=user_message,
                extra_tools=[
                    self._make_search_tool(project.id, self.db),
                    self._make_graph_tool(project.id),
                ],
                sandbox_path=repo_path,
                repo_path=repo_path,
            )
            if result:
                try:
                    return json.loads(self._extract_json(result))
                except (json.JSONDecodeError, ValueError):
                    pass  # fall through to single-shot

        # ── Fallback: single-shot LLM with parsed codebase context ────────────
        await self._emit_log("info", "Architecture falling back to single-shot LLM")
        file_listing = self._build_file_listing(codebase)
        symbols_summary = self._build_symbols_summary(codebase)
        languages = (
            ", ".join(f"{lang} ({n})" for lang, n in codebase.languages.items())
            if codebase else "unknown"
        )
        messages = ARCHITECTURE_ANALYSIS.render(
            project_name=project.name,
            languages=languages,
            file_count=str(codebase.total_files if codebase else 0),
            file_listing=file_listing,
            symbols_summary=symbols_summary,
        )
        result = await self._call_llm_json(messages, task_type="architecture") or {}
        return result if result else self._fallback_map(codebase, project.name)

    # ── Context formatters ────────────────────────────────────────────────────

    def _format_api_context(self, api_specs: list) -> str:
        if not api_specs:
            return ""
        return "\n".join(s.summary() if hasattr(s, "summary") else str(s) for s in api_specs[:3])

    def _format_infra_context(self, infra_context: list) -> str:
        if not infra_context:
            return ""
        return "\n".join(i.summary() if hasattr(i, "summary") else str(i) for i in infra_context[:5])

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
        return "\n".join(
            f"  {f.path}: {', '.join(s['name'] for s in f.symbols[:6])}"
            for f in codebase.files[:15] if f.symbols
        )

    def _fallback_map(self, codebase, project_name: str) -> dict:
        lang = codebase.primary_language if codebase else "unknown"
        return {
            "services": [{"name": project_name, "type": "application", "description": "", "files": []}],
            "tech_stack": {"language": lang or "unknown", "frameworks": [], "databases": [], "infra": []},
            "patterns": [],
            "entry_points": [],
            "external_dependencies": [],
        }
