from __future__ import annotations

import json
import re
from pathlib import Path
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
        documentation_plan: dict = state.get("documentation_plan") or {}

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
                        doc_type, project, codebase, architecture_map, strategy,
                        sandbox, repo_path, documentation_plan
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
        sandbox, repo_path: str = "", documentation_plan: dict | None = None
    ) -> str:
        # ── Try ReAct if we have an actual repo path ───────────────────────────
        if repo_path:
            strategy_hint = self._strategy_hint(strategy, doc_type)
            arch_summary = self._arch_summary(architecture_map)
            file_listing = self._summarize_structure(codebase)
            section_plan = self._section_plan_for(documentation_plan, doc_type)
            planned = self._planned_sections(documentation_plan, doc_type)

            user_message = (
                f"Write a complete '{doc_type}' documentation for project '{project.name}'.\n\n"
                f"Repository: {repo_path}\n\n"
                f"IMPORTANT: Every file path you read MUST start exactly with: {repo_path}\n"
                f"Do not construct or guess paths under any other directory.\n\n"
                f"Known files:\n{file_listing}\n\n"
                f"Architecture context:\n{arch_summary}\n\n"
                f"Sections to write:\n{section_plan}\n\n"
                f"Documentation guidance:\n{strategy_hint}\n\n"
                "Instructions:\n"
                "1. For each section listed above, FIRST read the key_files for that section using the filesystem tools.\n"
                "2. Then call write_section(section_name, content) with the written content.\n"
                "3. Begin each section's content with a Markdown H2 heading: '## Section Name'.\n"
                "4. Repeat for every section before giving your final answer.\n"
                "5. Use exact paths from the Known files list above. Never guess paths.\n"
                "6. Your final answer should be a brief summary of sections written, not the full content."
            )

            # write_section tool: each call saves one section file to sandbox
            sections_dir = sandbox.outputs / doc_type if sandbox else None
            written_sections: list[str] = []
            completed: dict[str, str] = {}  # section_name(lower) -> status note

            # Seed progress.md with the FULL plan up-front, so every TODO section is
            # visible before any writing happens (checked off as each completes).
            if sections_dir is not None:
                try:
                    sections_dir.mkdir(parents=True, exist_ok=True)
                    (sections_dir / "progress.md").write_text(
                        self._render_progress(doc_type, planned, completed), encoding="utf-8"
                    )
                except Exception:
                    pass

            from langchain_core.tools import tool as lc_tool

            @lc_tool
            def write_section(section_name: str, content: str) -> str:
                """Write one documentation section to disk. Call once per section."""
                if sections_dir is None:
                    return f"Section '{section_name}' captured (no sandbox)"
                try:
                    sections_dir.mkdir(parents=True, exist_ok=True)
                    safe = re.sub(r"[^\w\-]", "_", section_name.lower())[:60]
                    idx = len(written_sections) + 1
                    section_file = sections_dir / f"{idx:02d}_{safe}.md"
                    # Heading-aware: add '## Name' only if the model didn't already write one
                    # (prevents both duplicate headings and missing headings).
                    body = content.lstrip()
                    if not body.startswith("#"):
                        body = f"## {section_name}\n\n{body}"
                    section_file.write_text(body, encoding="utf-8")
                    written_sections.append(str(section_file))
                    completed[section_name.lower().strip()] = f"written ({len(content)} chars)"
                    # Re-render progress.md: planned TODOs + completed checkmarks
                    (sections_dir / "progress.md").write_text(
                        self._render_progress(doc_type, planned, completed), encoding="utf-8"
                    )
                    return f"Section '{section_name}' written ({len(content)} chars)"
                except Exception as exc:
                    return f"Error writing section '{section_name}': {exc}"

            result = await self._run_react(
                system_prompt=_WRITER_SYSTEM_PROMPT,
                user_message=user_message,
                extra_tools=[self._make_search_tool(project.id, self.db), write_section],
                sandbox_path=repo_path,
            )

            # Assemble final content from saved section files (preferred) or raw answer
            combined = self._collect_sections(sections_dir, written_sections) if written_sections else result
            if combined and len(combined) > 200:
                try:
                    sandbox.output_path(doc_type).write_text(combined, encoding="utf-8")
                    self._save_memory_checkpoint(sandbox, f"writer_{doc_type}", {
                        "doc_type": doc_type,
                        "sections": len(written_sections),
                        "content_preview": combined[:500],
                        "length": len(combined),
                    })
                except Exception:
                    pass
                return combined

        # ── Fallback: single-shot LLM ─────────────────────────────────────────
        await self._emit_log("info", f"Writer falling back to single-shot for {doc_type}")
        section_plan = self._section_plan_for(documentation_plan, doc_type)
        content = await self._generate_doc_single_shot(
            doc_type, project, codebase, architecture_map, strategy, section_plan
        )
        if content and sandbox:
            try:
                sandbox.output_path(doc_type).write_text(content, encoding="utf-8")
                self._save_memory_checkpoint(sandbox, f"writer_{doc_type}", {
                    "doc_type": doc_type,
                    "content_preview": content[:500],
                    "length": len(content),
                    "method": "single_shot",
                })
            except Exception:
                pass
        return content

    async def _generate_doc_single_shot(
        self, doc_type: str, project, codebase, architecture_map: dict, strategy: dict,
        section_plan: str = ""
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
            section_hint = f"\n\nSections to write:\n{section_plan}" if section_plan else ""
            messages = [
                {"role": "system", "content": "You are a senior technical writer."},
                {
                    "role": "user",
                    "content": (
                        f"Write a comprehensive {doc_type} document for project '{project.name}'.\n\n"
                        f"Architecture context:\n{arch_summary}\n\n"
                        f"Documentation guidance:\n{strategy_hint}"
                        f"{section_hint}"
                    ),
                },
            ]

        return await self._call_llm(messages, task_type="write")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _collect_sections(self, sections_dir: Path | None, written: list[str]) -> str:
        """Concatenate numbered section files into one markdown document."""
        if not sections_dir or not written:
            return ""
        parts: list[str] = []
        for path_str in written:
            try:
                parts.append(Path(path_str).read_text(encoding="utf-8"))
            except Exception:
                pass
        return "\n\n".join(parts)

    def _planned_sections(self, documentation_plan: dict | None, doc_type: str) -> list[dict]:
        """Return the structured section list (name/focus/key_files) for this doc_type."""
        if documentation_plan:
            for doc in documentation_plan.get("documents", []):
                if doc.get("type") == doc_type:
                    return doc.get("sections", []) or []
        return []

    def _render_progress(self, doc_type: str, planned: list[dict], completed: dict[str, str]) -> str:
        """Render progress.md: all planned sections as a checklist, ticked as completed.

        `completed` maps lower-cased section name -> status note (e.g. 'written (1234 chars)').
        """
        lines = [f"# {doc_type.title()} — Writing Progress", ""]
        lines.append(f"Plan: {len(planned)} section(s) to write. Each is read-then-write.")
        lines.append("")
        rendered: set[str] = set()
        for sec in planned:
            name = sec.get("name", "")
            focus = sec.get("focus", "")
            key = name.lower().strip()
            rendered.add(key)
            if key in completed:
                lines.append(f"- [x] {name} — {completed[key]}")
            else:
                suffix = f": {focus}" if focus else ""
                lines.append(f"- [ ] {name}{suffix}")
        # Any sections the writer produced that weren't in the plan
        for key, note in completed.items():
            if key not in rendered:
                lines.append(f"- [x] {key} — {note}")
        return "\n".join(lines)

    def _section_plan_for(self, documentation_plan: dict | None, doc_type: str) -> str:
        if not documentation_plan:
            return "(no section plan — write comprehensive sections based on the architecture)"
        for doc in documentation_plan.get("documents", []):
            if doc.get("type") == doc_type:
                lines = [f"Write these sections in order:"]
                for s in doc.get("sections", []):
                    name = s.get("name", "")
                    focus = s.get("focus", "")
                    key_files = s.get("key_files", [])
                    files_hint = f" [key files: {', '.join(key_files)}]" if key_files else ""
                    lines.append(f"  - {name}: {focus}{files_hint}")
                return "\n".join(lines)
        return "(no section plan — write comprehensive sections based on the architecture)"

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
