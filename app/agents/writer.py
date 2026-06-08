import json
from typing import Any
from app.agents.base import BaseAgent
from app.llm.prompts.writer_prompts import ARCHITECTURE_DOC, MODULE_DOC


class WriterAgent(BaseAgent):
    name = "writer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        await self._emit_log("info", "WriterAgent started")
        await self._update_step(self.name, "running")

        project = state["project"]
        codebase = state.get("codebase")
        doc_types: list[str] = state.get("doc_types", ["architecture"])

        generated_docs: list[dict] = state.get("generated_docs", [])

        for doc_type in doc_types:
            try:
                content = await self._generate_doc(doc_type, project, codebase)
                generated_docs.append({
                    "doc_type": doc_type,
                    "title": self._title_for(doc_type, project.name),
                    "content_markdown": content,
                })
                await self._emit_log("info", f"Generated {doc_type} document")
            except Exception as exc:
                await self._emit_log("error", f"Failed to generate {doc_type}: {exc}")

        await self._update_step(self.name, "completed", {"doc_count": len(generated_docs)})
        return {**state, "generated_docs": generated_docs}

    async def _generate_doc(self, doc_type: str, project, codebase) -> str:
        if doc_type == "architecture":
            messages = ARCHITECTURE_DOC.render(
                project_name=project.name,
                repo_structure=self._summarize_structure(codebase),
                languages=self._languages_str(codebase),
                symbols_summary=self._symbols_summary(codebase),
            )
        elif doc_type == "module" and codebase:
            # Write one doc per file (simplified — Phase 2 will fan-out per file)
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
                {"role": "system", "content": "You are a technical writer."},
                {"role": "user", "content": f"Write a {doc_type} document for project '{project.name}'."},
            ]

        return await self._call_llm(messages, task_type="write")

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
