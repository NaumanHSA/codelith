import json
from typing import Any
from app.agents.base import BaseAgent
from app.llm.prompts.writer_prompts import ARCHITECTURE_DOC, MODULE_DOC


class WriterAgent(BaseAgent):
    name = "writer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        project = state["project"]
        codebase = state.get("codebase")
        architecture_map: dict = state.get("architecture_map", {})
        strategy: dict = state.get("strategy", {})

        # When invoked via Send fan-out, current_doc_type is set per-writer.
        # Fall back to iterating doc_types for direct (non-fan-out) invocation.
        single_type: str | None = state.get("current_doc_type")
        doc_types: list[str] = [single_type] if single_type else state.get("doc_types", ["architecture"])

        await self._emit_log("info", "WriterAgent started", doc_types=doc_types)
        await self._update_step(self.name, "running")

        new_docs: list[dict] = []
        for doc_type in doc_types:
            try:
                content = await self._generate_doc(doc_type, project, codebase, architecture_map, strategy)
                new_docs.append({
                    "doc_type": doc_type,
                    "title": self._title_for(doc_type, project.name),
                    "content_markdown": content,
                })
                await self._emit_log("info", f"Generated {doc_type} document")
            except Exception as exc:
                await self._emit_log("error", f"Failed to generate {doc_type}: {exc}")

        await self._update_step(self.name, "completed", {"doc_count": len(new_docs)})
        # Return only new_docs — the Annotated[list, operator.add] in state merges them
        return {"generated_docs": new_docs}

    async def _generate_doc(
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
        return "\n".join(lines)

    def _strategy_hint(self, strategy: dict, doc_type: str) -> str:
        hints = strategy.get("template_hints", [])
        for h in hints:
            if h.get("doc_type") == doc_type:
                sections = h.get("sections", [])
                return "Sections to cover: " + ", ".join(sections)
        return ""

    def _title_for(self, doc_type: str, project_name: str) -> str:
        titles = {
            "architecture": f"{project_name} — Architecture Documentation",
            "api": f"{project_name} — API Reference",
            "module": f"{project_name} — Module Documentation",
            "tutorial": f"{project_name} — Getting Started Tutorial",
            "runbook": f"{project_name} — Runbook",
        }
        return titles.get(doc_type, f"{project_name} — {doc_type.title()} Documentation")

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
