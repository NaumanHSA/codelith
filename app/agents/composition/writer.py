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

**Page mode changes only the level.** When the job writes site pages, the graph sends
one writer per page and everything below runs unchanged, one level deeper: what was
"sections of a document" is now "headings of a page". The one genuine addition is that
each page's prompt names what the *other* pages of the site cover, because duplication
across pages cannot be spotted from inside a single page the way duplication within a
document can.
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
from app.tracing.artifacts import (
    save_artifact,
    save_input_text_artifact,
    save_text_artifact,
)

#: The model's way of saying the packed context was not enough.
_NEED_CONTEXT = re.compile(r"^\s*NEED_CONTEXT:\s*(.+)$", re.IGNORECASE)


class CompositionWriterAgent(BaseAgent):
    name = "composition_writer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        # Fan-out sets exactly one of these. `current_page` means page mode; without
        # either, write everything requested (the path the tests and legacy graph use).
        page = state.get("current_page")
        if page:
            targets = [page]
        elif state.get("pages"):
            targets = list(state["pages"])
        else:
            single = state.get("current_doc_type")
            doc_types = [single] if single else (state.get("doc_types") or ["architecture"])
            targets = [{"doc_type": dt} for dt in doc_types]

        label = ", ".join(t.get("address") or t["doc_type"] for t in targets)
        tracer = self._tracer()

        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message=f"Writer: {label}",
            end_message="Writer: complete",
            inputs={"targets": label},
        ) as t:
            await self._update_step(self.name, "running")

            settings = get_settings()
            project = state["project"]
            kb_id = state["kb_id"]
            plans: dict = state.get("documentation_plan") or {}
            strategy: dict = state.get("strategy") or {}
            site_map: dict = state.get("site_map") or {}

            builder = SectionContextBuilder(
                db=self.db,
                kb_id=kb_id,
                project_id=project.id,
                token_budget=settings.COMPOSITION_SECTION_TOKEN_BUDGET,
            )

            docs: list[dict] = []
            for target in targets:
                doc_type = target["doc_type"]
                address = target.get("address")
                plan = plans.get(address or doc_type) or {}
                sections = plan.get("sections") or []
                if not sections:
                    await self._emit_log(
                        "warning", f"No sections planned for {address or doc_type}"
                    )
                    continue

                content = await self._write_doc(
                    address or doc_type, doc_type, sections, project, strategy,
                    builder, settings,
                    neighbours=self._neighbours(site_map, address) if address else "",
                    page=target if address else None,
                )
                doc = {
                    "doc_type": doc_type,
                    "title": plan.get("title") or f"{project.name} — {doc_type.title()}",
                    "content_markdown": content,
                }
                if address:
                    # Carried through diagram/qa/formatter untouched, and read by the
                    # publisher to write the page back with its provenance.
                    doc |= {
                        "page_id": target["id"],
                        "address": address,
                        "section_slug": target["section_slug"],
                        "slug": target["slug"],
                        "source_files": self._source_files(sections),
                    }
                docs.append(doc)
                await self._emit_log(
                    "info", f"Wrote {address or doc_type} ({len(content)} chars)"
                )

            t.outputs(doc_count=len(docs))
            await self._update_step(self.name, "completed", {"doc_count": len(docs)})
            return {"generated_docs": docs}

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _source_files(sections: list[dict]) -> list[str]:
        """
        Every file this page was actually anchored on, deduped in plan order.

        Recorded on the page so S5 can diff a new commit against it and mark exactly
        the pages that change invalidated — and so a reader can be told, today, which
        files a claim came from.
        """
        files: list[str] = []
        for section in sections:
            files.extend(section.get("key_files") or [])
        return list(dict.fromkeys(files))

    @staticmethod
    def _neighbours(site_map: dict, address: str) -> str:
        """
        What the rest of the site covers, so this page does not cover it again.

        Addresses are included because they are also the link targets: this list is
        the entire vocabulary of `[[section/page]]` references the writer is allowed
        to use, and the linker drops anything outside it.
        """
        lines: list[str] = []
        for section in site_map.get("sections") or []:
            for page in section.get("pages") or []:
                other = f"{section.get('slug')}/{page.get('slug')}"
                if other == address:
                    continue
                intent = (page.get("intent") or "").strip()
                lines.append(
                    f"[[{other}]] {page.get('title')}" + (f" — {intent}" if intent else "")
                )
        return "; ".join(lines)

    async def _write_doc(
        self, label, doc_type, sections, project, strategy, builder, settings,
        neighbours: str = "",
        page: dict | None = None,
    ) -> str:
        audience, tone = self._voice(strategy, doc_type)

        # Phase 1: retrieval, sequential — one shared DB session.
        contexts: list[SectionContext] = []
        for section in sections:
            # Retrieval is cheap but a whole document's worth adds up; bail early.
            await check_cancelled()
            contexts.append(await builder.build(section, doc_type))
        for section, context in zip(sections, contexts, strict=True):
            # The exact bundle the model was shown — the single most useful artifact
            # when a section comes out thin or wrong.
            save_input_text_artifact(
                f"writer.{label}.{section.get('name', 'section')}.context",
                context.render(),
            )
        save_artifact(
            f"writer.{label}.context_stats",
            [
                {
                    "section": c.section_name,
                    "tokens": c.tokens,
                    "key_files": c.key_files,
                    "module_summaries": len(c.module_summaries),
                    "narratives": len(c.narratives),
                    "source_blocks": len(c.source_blocks),
                    "retrieved_blocks": len(c.retrieved_blocks),
                    "is_thin": c.is_thin,
                }
                for c in contexts
            ],
        )

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
                    audience, tone, outline, builder, neighbours, page, settings,
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
                save_text_artifact(f"writer.{label}.{name}.section", outcome)
                parts.append(outcome)
        document = "\n\n".join(parts)
        save_text_artifact(f"writer.{label}.document", document)
        return document

    async def _write_section(
        self, section, context, doc_type, project, audience, tone, outline, builder,
        neighbours: str = "",
        page: dict | None = None,
        settings=None,
    ) -> str:
        name = section.get("name", "Section")
        ask = (
            section, context, doc_type, project, audience, tone, outline,
            neighbours, page, settings,
        )
        body = await self._ask(*ask)

        # Bounded escape hatch: one extra retrieval when the model says it lacks context.
        need = _NEED_CONTEXT.match(body.strip()) if body else None
        if need:
            query = need.group(1).strip()
            await self._emit_log("info", f"Section '{name}' requested more context: {query}")
            extra = await builder.search(query, limit=6, exclude=context.key_files)
            if extra:
                context.retrieved_blocks.extend(extra)
            body = await self._ask(*ask)
            if _NEED_CONTEXT.match((body or "").strip()):
                # Only one retry — do not let this become an exploration loop.
                await self._emit_log("warning", f"Section '{name}' still lacks context")
                body = ""

        if not body:
            return ""
        body = body.lstrip()
        return body if body.startswith("#") else f"## {name}\n\n{body}"

    async def _ask(
        self, section, context, doc_type, project, audience, tone, outline,
        neighbours: str = "",
        page: dict | None = None,
        settings=None,
    ) -> str:
        settings = settings or get_settings()
        name = section.get("name", "Section")
        others = [n for n in outline if n and n != name]
        already = ""
        if others:
            already += (
                f"The other sections here cover: {', '.join(others)}. "
                "Do not duplicate them.\n\n"
            )
        if neighbours:
            # The cross-page rule. A writer that cannot see that `api/auth` exists
            # will explain authentication again, and nothing downstream can tell
            # that it did.
            already += (
                "Other pages of this documentation site, with the reference to use "
                f"for each: {neighbours}. They are being written separately — link "
                "to them, do not restate them.\n\n"
            )

        # Doc-type mode has no page, so the heading is told it belongs to the document
        # rather than being given a page identity it does not have.
        page_title = (page or {}).get("title") or f"{doc_type.replace('_', ' ').title()}"
        page_intent = (page or {}).get("intent") or "part of this documentation"

        messages = SECTION_WRITE.render(
            doc_type=doc_type,
            project_name=project.name,
            page_title=page_title,
            page_intent=page_intent,
            section_name=name,
            focus=section.get("focus") or name,
            heading_count=str(len(outline) or 1),
            word_budget=str(settings.SITE_WORDS_PER_HEADING),
            max_subheadings=str(settings.SITE_MAX_SUBHEADINGS_PER_SECTION),
            overview_steer=self._overview_steer(page),
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

    #: Slugs and titles that mean "this page is about the whole system".
    _OVERVIEW_HINTS = ("overview", "introduction", "architecture", "index", "about")

    @classmethod
    def _overview_steer(cls, page: dict | None) -> str:
        """
        The extra rule for overview-shaped pages, and only for them.

        This is the page type that goes wrong. C1 measured `architecture/overview`
        planning four headings that each covered a different *other* section of the
        site — with the anti-duplication paragraph rendering correctly. Being told not
        to duplicate is not the same as being told what an overview is for, so this
        says the second thing, and says it only where it applies: a rule this strong
        on a reference page would make it refuse to explain anything.
        """
        if not page:
            return ""
        haystack = f"{page.get('slug', '')} {page.get('title', '')}".lower()
        if not any(h in haystack for h in cls._OVERVIEW_HINTS):
            return ""
        return (
            "  - **This is an overview page.** Its job is to explain how the parts "
            "relate to each other and to send the reader to the page that documents "
            "each one. Name a component, say what it is for and how it connects to "
            "the others, then link to its page with `[[section/page]]` and move on. "
            "Do not explain how any single component works internally — that is the "
            "other page's job, it is being written separately, and a reader who meets "
            "the same explanation twice trusts neither.\n"
        )

    @staticmethod
    def _voice(strategy: dict, doc_type: str) -> tuple[str, str]:
        for entry in strategy.get("audiences") or []:
            if entry.get("doc_type") == doc_type:
                return entry.get("audience", "developers"), entry.get("tone", "technical")
        return "developers", "technical"
