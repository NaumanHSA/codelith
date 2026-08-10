from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from codelith.agents.base import BaseAgent
from codelith.agents.react_mixin import ReActMixin
from codelith.config import get_settings
from codelith.llm.prompts.writer_prompts import ARCHITECTURE_DOC, MODULE_DOC

_SECTION_SYSTEM_PROMPT = """\
You are a senior technical writer. You write ONE documentation section at a time.

Process:
1. Read the key files listed for this section using the filesystem tools (2-4 reads is enough).
2. Use search_codebase if you need to locate something not in the key files.
3. Then write the section in Markdown.

Your FINAL ANSWER must be the section content itself — nothing else. No preamble like
"Here is the section", no summary of what you did. Start with a '## Section Name' heading.

Be precise — only document what you can confirm from the code you actually read.
Do not invent features or APIs. Use fenced code blocks for examples.
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
        # ── Section-by-section via small per-section ReAct loops ──────────────
        if repo_path:
            planned = self._planned_sections(documentation_plan, doc_type) \
                or self._fallback_sections(strategy, doc_type)
            arch_summary = self._arch_summary(architecture_map)
            file_listing = self._summarize_structure(codebase)

            sections_dir = sandbox.outputs / doc_type if sandbox else None
            completed: dict[str, str] = {}
            written_files: list[str] = []
            written_titles: list[str] = []

            # Seed progress.md with the FULL plan up-front: all TODO sections visible
            # before any writing happens, checked off as each completes.
            if sections_dir is not None:
                try:
                    sections_dir.mkdir(parents=True, exist_ok=True)
                    (sections_dir / "progress.md").write_text(
                        self._render_progress(doc_type, planned, completed), encoding="utf-8"
                    )
                except Exception:
                    pass

            for idx, section in enumerate(planned, start=1):
                name = section.get("name", f"Section {idx}")
                await self._emit_log("info", f"Writing section '{name}' ({idx}/{len(planned)})")

                content = await self._write_section_react(
                    section, doc_type, project, repo_path,
                    arch_summary, file_listing, written_titles,
                )
                if not content or len(content.strip()) < 150:
                    await self._emit_log(
                        "warning", f"Section '{name}' loop gave no usable content — single-shot fallback"
                    )
                    content = await self._generate_section_single_shot(
                        section, doc_type, project, arch_summary
                    )

                # Heading rule: prepend '## Name' only if the model didn't write one
                body = content.lstrip()
                if not body.startswith("#"):
                    body = f"## {name}\n\n{body}"

                if sections_dir is not None:
                    try:
                        safe = re.sub(r"[^\w\-]", "_", name.lower())[:60]
                        section_file = sections_dir / f"{idx:02d}_{safe}.md"
                        section_file.write_text(body, encoding="utf-8")
                        written_files.append(str(section_file))
                        completed[name.lower().strip()] = f"written ({len(body)} chars)"
                        (sections_dir / "progress.md").write_text(
                            self._render_progress(doc_type, planned, completed), encoding="utf-8"
                        )
                    except Exception:
                        pass

                written_titles.append(name)
                await self._emit_log("info", f"Section '{name}' written ({len(body)} chars)")

            combined = self._collect_sections(sections_dir, written_files)
            if combined and len(combined) > 200:
                try:
                    sandbox.output_path(doc_type).write_text(combined, encoding="utf-8")
                    self._save_memory_checkpoint(sandbox, f"writer_{doc_type}", {
                        "doc_type": doc_type,
                        "sections": len(written_files),
                        "content_preview": combined[:500],
                        "length": len(combined),
                    })
                except Exception:
                    pass
                return combined

        # ── Fallback: single-shot LLM for the whole doc (no repo / all sections failed)
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

    async def _write_section_react(
        self, section: dict, doc_type: str, project, repo_path: str,
        arch_summary: str, file_listing: str, written_titles: list[str],
    ) -> str:
        """One small ReAct loop for one section: read key files, return the section text."""
        settings = get_settings()
        name = section.get("name", "")
        focus = section.get("focus", "")
        key_files = section.get("key_files", []) or []
        key_files_text = (
            "\n".join(f"  {repo_path}/{kf.lstrip('/')}" for kf in key_files[:5])
            if key_files else "  (none listed — use list_project_root and search_codebase to find them)"
        )
        prior = (
            "Sections already written (do NOT repeat their content): "
            + ", ".join(written_titles) + "\n\n"
        ) if written_titles else ""

        user_message = (
            f"Write the '{name}' section of the {doc_type} documentation "
            f"for project '{project.name}'.\n\n"
            f"Section focus: {focus or name}\n\n"
            f"Repository: {repo_path}\n"
            f"IMPORTANT: Every file path you read MUST start exactly with: {repo_path}\n\n"
            f"Key files for this section:\n{key_files_text}\n\n"
            f"Known files:\n{file_listing}\n\n"
            f"Architecture context:\n{arch_summary}\n\n"
            f"{prior}"
            "Read the key files, then respond with the finished section in Markdown, "
            f"starting with '## {name}'. Your final answer IS the section content."
        )

        return await self._run_react(
            system_prompt=_SECTION_SYSTEM_PROMPT,
            user_message=user_message,
            extra_tools=[self._make_search_tool(project.id, self.db)],
            sandbox_path=repo_path,
            max_iterations=settings.REACT_SECTION_MAX_ITERATIONS,
        )

    async def _generate_section_single_shot(
        self, section: dict, doc_type: str, project, arch_summary: str
    ) -> str:
        """No-tools fallback for a single section when its ReAct loop fails."""
        name = section.get("name", "")
        focus = section.get("focus", "")
        messages = [
            {"role": "system", "content": "You are a senior technical writer. Write in Markdown."},
            {
                "role": "user",
                "content": (
                    f"Write the '{name}' section of the {doc_type} documentation "
                    f"for project '{project.name}'.\n\n"
                    f"Section focus: {focus or name}\n\n"
                    f"Architecture context:\n{arch_summary}\n\n"
                    f"Start with '## {name}'. Only include facts supported by the context above; "
                    "keep it brief where the context is thin rather than inventing details."
                ),
            },
        ]
        try:
            return await self._call_llm(messages, task_type="write")
        except Exception:
            return f"## {name}\n\n_(Section could not be generated.)_"

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

    def _fallback_sections(self, strategy: dict, doc_type: str) -> list[dict]:
        """Derive a section list from strategy hints when the planner gave none."""
        for h in strategy.get("template_hints", []):
            if h.get("doc_type") == doc_type and h.get("sections"):
                return [{"name": s, "focus": s, "key_files": []} for s in h["sections"]]
        return [{"name": s, "focus": s, "key_files": []} for s in ("Overview", "Architecture", "Usage")]

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
                lines = ["Write these sections in order:"]
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
