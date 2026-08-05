"""
Retrieve-then-write.

The measured problem this replaces: the previous writer ran a ReAct loop per section
with filesystem tools, producing 21 `read_text_file` calls, zero uses of the retrieval
layer, one `npx` MCP server spawned per section, and 55% of total job runtime — for
one document.

Here each section is handled as: build its context in Python, then make one LLM call.
Retrieval is still available at write time, because the knowledge base is a summary
and will sometimes be too thin — but as a single bounded follow-up query the model
must ask for explicitly, not an open exploration loop.

Two ordering rules matter and are load-bearing:

  1. Every section's context is built *before* generation fans out. Building inside the
     gather would share one AsyncSession across tasks, which raises "another operation
     is in progress" (the bug that silently dropped narratives in Phase B).
  2. Sections are generated concurrently but assembled in plan order.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from app.agents.base import BaseAgent
from app.config import get_settings
from app.core.cancellation import JobCancelled, check_cancelled
from app.knowledge.retrieval import SectionContext, SectionContextBuilder
from app.llm.prompts.composition_prompts import SECTION_WRITE

#: The model's way of saying the packed context was not enough.
_NEED_CONTEXT = re.compile(r"^\s*NEED_CONTEXT:\s*(.+)$", re.IGNORECASE)


class CompositionWriterAgent(BaseAgent):
    name = "composition_writer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        # Fan-out sets current_doc_type; otherwise write every requested type.
        single = state.get("current_doc_type")
        doc_types = [single] if single else (state.get("doc_types") or ["architecture"])

        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message=f"Writer: {doc_types}",
            end_message="Writer: complete",
            inputs={"doc_types": doc_types},
        ) as t:
            await self._update_step(self.name, "running")

            settings = get_settings()
            project = state["project"]
            kb_id = state["kb_id"]
            plans: dict = state.get("documentation_plan") or {}
            strategy: dict = state.get("strategy") or {}

            builder = SectionContextBuilder(
                db=self.db,
                kb_id=kb_id,
                project_id=project.id,
                token_budget=settings.COMPOSITION_SECTION_TOKEN_BUDGET,
            )

            docs: list[dict] = []
            for doc_type in doc_types:
                plan = plans.get(doc_type) or {}
                sections = plan.get("sections") or []
                if not sections:
                    await self._emit_log("warning", f"No sections planned for {doc_type}")
                    continue

                content = await self._write_doc(
                    doc_type, sections, project, strategy, builder, settings
                )
                docs.append(
                    {
                        "doc_type": doc_type,
                        "title": plan.get("title") or f"{project.name} — {doc_type.title()}",
                        "content_markdown": content,
                    }
                )
                await self._emit_log("info", f"Wrote {doc_type} ({len(content)} chars)")

            t.outputs(doc_count=len(docs))
            await self._update_step(self.name, "completed", {"doc_count": len(docs)})
            return {"generated_docs": docs}

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _write_doc(
        self, doc_type, sections, project, strategy, builder, settings
    ) -> str:
        audience, tone = self._voice(strategy, doc_type)

        # Phase 1: retrieval, sequential — one shared DB session.
        contexts: list[SectionContext] = []
        for section in sections:
            # Retrieval is cheap but a whole document's worth adds up; bail early.
            await check_cancelled()
            contexts.append(await builder.build(section, doc_type))
        await self._emit_log(
            "info",
            f"Built context for {len(contexts)} sections",
            tokens=[c.tokens for c in contexts],
        )

        # Phase 2: generation, concurrent — no DB access inside.
        outline = [s.get("name", "") for s in sections]
        semaphore = asyncio.Semaphore(settings.COMPOSITION_SECTION_CONCURRENCY)

        async def generate(index: int) -> str:
            async with semaphore:
                # Queued sections must not start once the user has cancelled.
                await check_cancelled()
                return await self._write_section(
                    sections[index], contexts[index], doc_type, project,
                    audience, tone, outline, builder,
                )

        results = await asyncio.gather(
            *(generate(i) for i in range(len(sections))), return_exceptions=True
        )

        # gather(return_exceptions=True) turns a cancellation into a value; surface it
        # before treating anything as a per-section failure.
        for outcome in results:
            if isinstance(outcome, JobCancelled):
                raise outcome

        parts: list[str] = []
        for section, outcome in zip(sections, results, strict=True):
            name = section.get("name", "Section")
            if isinstance(outcome, BaseException):
                await self._emit_log(
                    "error",
                    f"Section '{name}' raised {type(outcome).__name__}: {outcome}",
                )
                continue
            if outcome:
                parts.append(outcome)
        return "\n\n".join(parts)

    async def _write_section(
        self, section, context, doc_type, project, audience, tone, outline, builder
    ) -> str:
        name = section.get("name", "Section")
        body = await self._ask(section, context, doc_type, project, audience, tone, outline)

        # Bounded escape hatch: one extra retrieval when the model says it lacks context.
        need = _NEED_CONTEXT.match(body.strip()) if body else None
        if need:
            query = need.group(1).strip()
            await self._emit_log("info", f"Section '{name}' requested more context: {query}")
            extra = await builder.search(query, limit=6, exclude=context.key_files)
            if extra:
                context.retrieved_blocks.extend(extra)
            body = await self._ask(
                section, context, doc_type, project, audience, tone, outline
            )
            if _NEED_CONTEXT.match((body or "").strip()):
                # Only one retry — do not let this become an exploration loop.
                await self._emit_log("warning", f"Section '{name}' still lacks context")
                body = ""

        if not body:
            return ""
        body = body.lstrip()
        return body if body.startswith("#") else f"## {name}\n\n{body}"

    async def _ask(self, section, context, doc_type, project, audience, tone, outline) -> str:
        name = section.get("name", "Section")
        others = [n for n in outline if n and n != name]
        already = (
            f"Other sections of this document cover: {', '.join(others)}. "
            "Do not duplicate them.\n\n"
            if others
            else ""
        )
        messages = SECTION_WRITE.render(
            doc_type=doc_type,
            project_name=project.name,
            section_name=name,
            focus=section.get("focus") or name,
            audience=audience,
            tone=tone,
            already_written=already,
            context=context.render(),
        )
        try:
            return (await self._call_llm(messages, task_type="write") or "").strip()
        except JobCancelled:
            raise  # must not be downgraded to "this section failed"
        except Exception as exc:
            await self._emit_log("warning", f"Section '{name}' generation failed: {exc}")
            return ""

    @staticmethod
    def _voice(strategy: dict, doc_type: str) -> tuple[str, str]:
        for entry in strategy.get("audiences") or []:
            if entry.get("doc_type") == doc_type:
                return entry.get("audience", "developers"), entry.get("tone", "technical")
        return "developers", "technical"
