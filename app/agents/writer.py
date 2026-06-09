from __future__ import annotations

import json
from typing import Any

from app.agents.base import BaseAgent
from app.agents.react_mixin import ReActMixin
from app.llm.prompts.writer_prompts import ARCHITECTURE_DOC, MODULE_DOC

_WRITER_SYSTEM_PROMPT = """\
You are a senior technical writer. Your task is to write comprehensive, accurate documentation
for a software project. You have access to tools to read source code files and search the codebase.

Before writing each section, look up the relevant source code:
- Use filesystem tools to read specific files
- Use search_codebase to find relevant code for a topic
- Read configs, README files, and entry points for context

Write in Markdown. Be precise — only document what you can confirm from the actual code.
Do not invent features or APIs that don't exist.

Structure the document with clear headings (##), code examples in fenced blocks, and concise prose.
"""


class WriterAgent(ReActMixin, BaseAgent):
    name = "writer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        project = state["project"]
        codebase = state.get("codebase")
        architecture_map: dict = state.get("architecture_map", {})
        strategy: dict = state.get("strategy", {})
        sandbox = state.get("sandbox")
        repo_path = state.get("repo_path") or ""

        # Fan-out: current_doc_type set by Send(); fallback to iterating doc_types
        single_type: str | None = state.get("current_doc_type")
        doc_types: list[str] = [single_type] if single_type else state.get("doc_types", ["architecture"])

        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message=f"WriterAgent: {doc_types}",
            end_message="WriterAgent: complete",
            inputs={"doc_types": doc_types},
        ) as t:
            await self._emit_log("info", "WriterAgent started", doc_types=doc_types)
            await self._update_step(self.name, "running")

            new_docs: list[dict] = []
            for doc_type in doc_types:
                try:
                    content = await self._write_doc(
                        doc_type, project, codebase, architecture_map, strategy, sandbox, repo_path
                    )
                    new_docs.append({
                        "doc_type": doc_type,
                        "title": self._title_for(doc_type, project.name),
                        "content_markdown": content,
                    })
                    await self._emit_log("info", f"Generated {doc_type} document")
                except Exception as exc:
                    await self._emit_log("error", f"Failed to generate {doc_type}: {exc}")

            t.outputs(doc_count=len(new_docs))
            await self._update_step(self.name, "completed", {"doc_count": len(new_docs)})
            # Return only new_docs — Annotated[list, operator.add] in state merges them
            return {"generated_docs": new_docs}

    async def _write_doc(
        self, doc_type: str, project, codebase, architecture_map: dict, strategy: dict,
        sandbox, repo_path: str = ""
    ) -> str:
        # ── Try ReAct if we have an actual repo path ───────────────────────────
        if repo_path:
            strategy_hint = self._strategy_hint(strategy, doc_type)
            arch_summary = self._arch_summary(architecture_map)

            file_listing = self._summarize_structure(codebase)
            user_message = (
                f"Write a complete '{doc_type}' documentation for project '{project.name}'.\n\n"
                f"Repository: {repo_path}\n\n"
                f"Known files:\n{file_listing}\n\n"
                f"Architecture context:\n{arch_summary}\n\n"
                f"Documentation guidance:\n{strategy_hint}\n\n"
                f"Read the files most relevant to '{doc_type}' before writing. "
                f"Do not list directories — the file list above is complete."
            )

            result = await self._run_react(
                system_prompt=_WRITER_SYSTEM_PROMPT,
                user_message=user_message,
                extra_tools=[self._make_search_tool(project.id, self.db)],
                sandbox_path=repo_path,
                repo_path=repo_path,
            )

            if result and len(result) > 200:
                # Persist to sandbox outputs + memory
                try:
                    sandbox.output_path(doc_type).write_text(result, encoding="utf-8")
                    self._save_memory_checkpoint(sandbox, f"writer_{doc_type}", {
                        "doc_type": doc_type,
                        "content_preview": result[:500],
                        "length": len(result),
                    })
                except Exception:
                    pass
                return result

        # ── Fallback: single-shot LLM ─────────────────────────────────────────
        await self._emit_log("info", f"Writer falling back to single-shot for {doc_type}")
        return await self._generate_doc_single_shot(doc_type, project, codebase, architecture_map, strategy)

    async def _generate_doc_single_shot(
        self, doc_type: str, project, codebase, architecture_map: dict, strategy: dict
    ) -> str:
        arch_summary = self._arch_summary(architecture_map)
        strategy_hint = self._strategy_hint(strategy, doc_type)

        if doc_type == "architecture":
            messages = ARCHITECTURE_DOC.render(
                project_name=project.name,
                repo_structure=self._summarize_structure(codebase),
                languages=self._languages_str(codebase),
                symbols_summary=self._symbols_summary(codebase),
            )
        elif doc_type == "module" and codebase:
            first_file = codebase.files[0] if codebase.files else None
            if not first_file:
                return "No source files found."
            messages = MODULE_DOC.render(
                file_path=first_file.path,
                language=first_file.language,
                source_code=first_file.content[:3000],
            )
        else:
            messages = [
                {"role": "system", "content": "You are a senior technical writer."},
                {
                    "role": "user",
                    "content": (
                        f"Write a comprehensive {doc_type} document for project '{project.name}'.\n\n"
                        f"Architecture context:\n{arch_summary}\n\n"
                        f"Documentation guidance:\n{strategy_hint}"
                    ),
                },
            ]

        return await self._call_llm(messages, task_type="write")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _title_for(self, doc_type: str, project_name: str) -> str:
        titles = {
            "architecture": f"{project_name} — Architecture Documentation",
            "api": f"{project_name} — API Reference",
            "module": f"{project_name} — Module Documentation",
            "tutorial": f"{project_name} — Getting Started Tutorial",
            "runbook": f"{project_name} — Runbook",
        }
        return titles.get(doc_type, f"{project_name} — {doc_type.title()} Documentation")

    def _arch_summary(self, architecture_map: dict) -> str:
        if not architecture_map:
            return "No architecture data."
        services = architecture_map.get("services", [])
        tech = architecture_map.get("tech_stack", {})
        lines = []
        if services:
            lines.append("Services: " + ", ".join(s["name"] for s in services[:6]))
        if tech.get("language"):
            lines.append(f"Language: {tech['language']}")
        if tech.get("frameworks"):
            lines.append("Frameworks: " + ", ".join(tech["frameworks"][:4]))
        if architecture_map.get("patterns"):
            lines.append("Patterns: " + ", ".join(architecture_map["patterns"][:4]))
        return "\n".join(lines)

    def _strategy_hint(self, strategy: dict, doc_type: str) -> str:
        for h in strategy.get("template_hints", []):
            if h.get("doc_type") == doc_type:
                sections = h.get("sections", [])
                return "Sections to cover: " + ", ".join(sections)
        return ""

    def _summarize_structure(self, codebase) -> str:
        if not codebase:
            return "No codebase parsed."
        lines = [f"Total files: {codebase.total_files}"]
        for f in codebase.files[:20]:
            lines.append(f"  {f.path} ({f.language})")
        if codebase.total_files > 20:
            lines.append(f"  ... and {codebase.total_files - 20} more files")
        return "\n".join(lines)

    def _languages_str(self, codebase) -> str:
        if not codebase:
            return "unknown"
        return ", ".join(f"{lang} ({count} files)" for lang, count in codebase.languages.items())

    def _symbols_summary(self, codebase) -> str:
        if not codebase:
            return ""
        lines = []
        for f in codebase.files[:10]:
            if f.symbols:
                symbol_names = ", ".join(s["name"] for s in f.symbols[:5])
                lines.append(f"{f.path}: {symbol_names}")
        return "\n".join(lines)
