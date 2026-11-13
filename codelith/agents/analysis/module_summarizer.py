"""
Per-module summaries — the expensive, reusable half of the knowledge base.

Runs once per commit. Every document type composed later reads these instead of
re-reading source, which is what makes choosing a second doc type cheap.

Summaries are produced concurrently with a bounded semaphore rather than one at a
time, and the module set is capped so a large repository cannot make analysis
unbounded.
"""

from __future__ import annotations

import asyncio
from typing import Any

from codelith.agents.base import BaseAgent
from codelith.config import get_settings
from codelith.core.cancellation import JobCancelled
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.knowledge import incremental
from codelith.knowledge.constants import ModuleRole
from codelith.llm.prompts.analysis_prompts import MODULE_SUMMARY
from codelith.tracing.artifacts import save_artifact

#: Roles not worth spending a summary on.
_SKIPPED_ROLES = {ModuleRole.TEST}


class ModuleSummarizerAgent(BaseAgent):
    name = "module_summarizer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="ModuleSummarizer: summarising modules",
            end_message="ModuleSummarizer: complete",
        ) as t:
            await self._update_step(self.name, "running")

            settings = get_settings()
            kb_id = state["kb_id"]
            repos = KnowledgeRepositories.for_session(self.db)

            modules = [
                m
                for m in await repos.modules.list_by_kb(kb_id)
                if m.role not in {str(r) for r in _SKIPPED_ROLES}
            ][: settings.ANALYSIS_MAX_SUMMARISED_MODULES]

            if not modules:
                await self._update_step(self.name, "completed", {"summarised": 0})
                return {"summarised_modules": 0}

            # Keep the last reading's summary of every module whose files are the same
            # files, unchanged. The rest is what the model is asked about.
            reuse = state.get("reuse") or {}
            kept, modules, rewritten = await self._keep_unchanged(repos, kb_id, modules, reuse)
            structure_unchanged = await self._structure_unchanged(repos, kb_id, reuse, rewritten)
            reuse = incremental.note(
                reuse,
                summaries_kept=kept,
                modules_rewritten=sorted(rewritten),
                structure_unchanged=structure_unchanged,
            )
            if kept:
                await self._emit_log(
                    "info",
                    f"Kept {kept} module summaries from the last reading; "
                    f"{len(modules)} to write",
                    kept=kept,
                    to_write=len(modules),
                )
            if not modules:
                await self.db.commit()
                await self._update_step(self.name, "completed", {"summarised": 0, "kept": kept})
                return {"summarised_modules": kept, "summary_failures": 0, "reuse": reuse}

            await self._emit_log("info", f"Summarising {len(modules)} modules")

            sources = self._source_lookup(state)
            semaphore = asyncio.Semaphore(settings.ANALYSIS_SUMMARY_CONCURRENCY)

            async def summarise(module) -> tuple[str, str | None]:
                async with semaphore:
                    return module.path, await self._summarise(module, sources, settings)

            results = await asyncio.gather(
                *(summarise(m) for m in modules), return_exceptions=True
            )

            for outcome in results:
                if isinstance(outcome, JobCancelled):
                    raise outcome

            written = failed = 0
            summaries: dict[str, str] = {}
            for module, outcome in zip(modules, results, strict=True):
                if isinstance(outcome, BaseException):
                    await self._emit_log(
                        "error",
                        f"Summary for '{module.path}' raised "
                        f"{type(outcome).__name__}: {outcome}",
                    )
                    failed += 1
                    continue
                path, summary = outcome
                if summary:
                    await repos.modules.set_summary(kb_id, path, summary)
                    summaries[path] = summary
                    written += 1
                else:
                    failed += 1
            await self.db.commit()

            save_artifact("module_summarizer.summaries", summaries)

            await self._emit_log(
                "info", f"Summarised {written}/{len(modules)} modules", failed=failed
            )
            t.outputs(summarised=written, failed=failed)
            await self._update_step(
                self.name, "completed", {"summarised": written, "failed": failed}
            )

            return {
                "summarised_modules": written + kept,
                "summary_failures": failed,
                "reuse": incremental.note(reuse, summaries_written=written),
            }

    # ── Reuse ─────────────────────────────────────────────────────────────────

    @staticmethod
    async def _keep_unchanged(repos, kb_id: int, modules, reuse: dict):
        """
        Copy summaries for modules that cannot have changed; return how many were
        kept, the modules still to summarise, and the paths of those.

        A module keeps its summary only when it is made of exactly the same files as
        before and none of them changed: a file moving in or out changes what the
        module is, even if every file in it is byte-for-byte the same.
        """
        if not incremental.active(reuse):
            return 0, modules, {m.path for m in modules}
        before = {
            m.path: m
            for m in await repos.modules.list_by_kb(reuse["from_kb"], include_tests=True, limit=5000)
            if (m.summary or "").strip()
        }
        kept = 0
        todo = []
        for module in modules:
            prev = before.get(module.path)
            if (
                prev is not None
                and list(prev.files_json) == list(module.files_json)
                and incremental.files_unchanged(reuse, module.files_json)
            ):
                await repos.modules.set_summary(kb_id, module.path, prev.summary)
                kept += 1
            else:
                todo.append(module)
        return kept, todo, {m.path for m in todo}

    @staticmethod
    async def _structure_unchanged(repos, kb_id: int, reuse: dict, rewritten: set[str]) -> bool:
        """
        Whether the overviews (architecture, site plan, questions) can be kept: the same
        modules as before, none re-summarised, and nothing outside every module touched
        — a manifest or a compose file is what the architecture's stack is read from.
        """
        if not incremental.active(reuse) or rewritten:
            return False
        now = await repos.modules.list_by_kb(kb_id, include_tests=True, limit=5000)
        before = await repos.modules.list_by_kb(reuse["from_kb"], include_tests=True, limit=5000)
        if {m.path for m in now if m.role != str(ModuleRole.TEST)} != {
            m.path for m in before if m.role != str(ModuleRole.TEST)
        }:
            return False
        in_modules = {f for m in [*now, *before] for f in m.files_json}
        return not any(p not in in_modules for p in incremental.touched(reuse))

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _summarise(self, module, sources: dict[str, str], settings) -> str | None:
        excerpt = self._excerpt(module, sources, settings.ANALYSIS_MODULE_CONTEXT_CHARS)
        messages = MODULE_SUMMARY.render(
            module_name=module.name,
            role=module.role,
            language=module.language or "unknown",
            files=", ".join(module.files_json[:12]) or "(none)",
            symbols=self._symbol_list(module),
            source=excerpt or "(source unavailable)",
        )
        try:
            summary = await self._call_llm(messages, task_type="summarize")
        except JobCancelled:
            raise
        except Exception as exc:
            await self._emit_log("warning", f"Summary failed for {module.path}: {exc}")
            return None
        return (summary or "").strip() or None

    @staticmethod
    def _symbol_list(module, limit: int = 40) -> str:
        public = [
            s for s in module.symbols_json if s.get("visibility") == "public"
        ] or module.symbols_json
        lines = [
            f"  {s.get('kind', '?')} {s.get('parent', '') + '.' if s.get('parent') else ''}"
            f"{s.get('name', '?')}"
            + (f"  — {s['docstring'].splitlines()[0]}" if s.get("docstring") else "")
            for s in public[:limit]
        ]
        return "\n".join(lines) or "  (no public symbols)"

    @staticmethod
    def _source_lookup(state: dict[str, Any]) -> dict[str, str]:
        codebase = state.get("codebase")
        return {f.path: f.content for f in (getattr(codebase, "files", None) or [])}

    @staticmethod
    def _excerpt(module, sources: dict[str, str], budget: int) -> str:
        """Head of each file, round-robin, until the character budget is spent."""
        paths = [p for p in module.files_json if p in sources][:8]
        if not paths:
            return ""
        per_file = max(400, budget // len(paths))
        parts = [f"--- {p} ---\n{sources[p][:per_file]}" for p in paths]
        return "\n\n".join(parts)[:budget]
