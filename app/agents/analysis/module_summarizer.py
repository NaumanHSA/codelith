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

from app.agents.base import BaseAgent
from app.config import get_settings
from app.core.cancellation import JobCancelled
from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.constants import ModuleRole
from app.llm.prompts.analysis_prompts import MODULE_SUMMARY

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
                    written += 1
                else:
                    failed += 1
            await self.db.commit()

            await self._emit_log(
                "info", f"Summarised {written}/{len(modules)} modules", failed=failed
            )
            t.outputs(summarised=written, failed=failed)
            await self._update_step(
                self.name, "completed", {"summarised": written, "failed": failed}
            )

            return {"summarised_modules": written, "summary_failures": failed}

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
