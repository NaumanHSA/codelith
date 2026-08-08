"""
Assembling the context a writer needs for one section.

This is the inversion Phase C is about. Previously the writer was given filesystem
tools and left to find its own context: measured on job 18 that was 21 `read_text_file`
calls, zero uses of the retrieval layer we had already built, an MCP server spawned per
section, and 55% of total runtime.

Here the pipeline does the retrieval — deterministically, in Python — and the model
does one thing: write. Retrieval is still available at write time (the knowledge base is
a summary and will sometimes be too thin), but as a bounded follow-up query rather than
an open-ended exploration loop.

Source text comes from `code_chunks`, not the filesystem: composition runs as a separate
job from analysis, so the cloned repository no longer exists on disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.policy import (
    CODE,
    DOCS_GENERATION,
    PROSE_TRUST,
    PROSE_TYPES,
    RetrievalPolicy,
)
from app.knowledge.narratives import topics_for_doc_type
from app.llm.client import create_embedding
from app.llm.context_manager import count_text_tokens
from app.memory.vector_store import VectorStore

#: Chunks fetched per section. Over-fetched on purpose: one embedding call produces
#: all of them, and the fill step decides how many actually fit.
_RETRIEVAL_CANDIDATES = 24

#: Per-narrative ceiling inside a section bundle. Section context competes with
#: verbatim source for the same budget, so narratives stay bounded here even though
#: strategy and the planner now read them whole.
_NARRATIVE_CHARS_IN_SECTION = 2000

#: Ceiling on module summaries in one bundle. They are the densest context we hold,
#: but they must not crowd out the verbatim source a section is written from.
_MAX_MODULE_SUMMARIES = 10

#: Prose candidates over-fetched per section. Smaller than the code pool: prose is
#: a router, and a handful of pointers is all routing needs.
_PROSE_CANDIDATES = 6


@dataclass(slots=True)
class SectionContext:
    """Everything handed to the model for one section, plus how it was obtained."""

    section_name: str
    module_summaries: list[str] = field(default_factory=list)
    narratives: list[str] = field(default_factory=list)
    source_blocks: list[str] = field(default_factory=list)
    retrieved_blocks: list[str] = field(default_factory=list)
    #: The repository's own prose. Separate from `retrieved_blocks` so it can never
    #: be mistaken for source, and so the trim order can drop it first.
    prose_blocks: list[str] = field(default_factory=list)
    key_files: list[str] = field(default_factory=list)
    tokens: int = 0

    @property
    def is_thin(self) -> bool:
        """Too little to write from — the caller should widen the search."""
        return not self.source_blocks and not self.retrieved_blocks

    def render(self) -> str:
        parts: list[str] = []
        if self.narratives:
            parts.append(
                "## What we already know about this system\n" + "\n\n".join(self.narratives)
            )
        if self.module_summaries:
            parts.append("## Relevant modules\n" + "\n".join(self.module_summaries))
        if self.source_blocks:
            parts.append("## Source for this section\n" + "\n\n".join(self.source_blocks))
        if self.retrieved_blocks:
            parts.append("## Additional retrieved source\n" + "\n\n".join(self.retrieved_blocks))
        if self.prose_blocks:
            # The heading is the warning. A model that reads this section has been
            # told, in the payload rather than in a system prompt, that these lines
            # are claims by a human and not observations of the code.
            parts.append(
                "## Existing documentation — UNVERIFIED, use only to locate code\n"
                "These were written by hand and may be out of date or wrong. Treat "
                "them as pointers to the source above, never as evidence for a "
                "statement.\n\n" + "\n\n".join(self.prose_blocks)
            )
        return "\n\n".join(parts) or "(no context available)"


class SectionContextBuilder:
    """
    Builds a token-bounded context bundle for a section.

    Deliberately synchronous-per-call and DB-bound: callers must build every section's
    context *before* fanning out generation. Sharing one `AsyncSession` across
    concurrent tasks raises "another operation is in progress" — the bug that silently
    dropped narratives in Phase B.
    """

    def __init__(
        self,
        db: AsyncSession,
        kb_id: int,
        project_id: int,
        token_budget: int = 6000,
        retrieval_policy: RetrievalPolicy = DOCS_GENERATION,
    ) -> None:
        self.db = db
        self.kb_id = kb_id
        self.project_id = project_id
        self.token_budget = token_budget
        # Defaults to code-only, so every existing caller — the writer, the reviser,
        # the planner — keeps behaving exactly as before. Opting into prose is an
        # explicit decision made by the consumer that can justify it.
        self.policy = retrieval_policy
        self.repos = KnowledgeRepositories.for_session(db)
        self.store = VectorStore(db)

    @property
    def code_budget(self) -> int:
        """
        Tokens reserved for code, which prose may not spend.

        This is the whole mechanism. A natural-language query is lexically closer to
        a paragraph of prose than to the function implementing it, so similarity
        ranking systematically favours prose — and asking a model to "prefer the
        code" is a soft constraint that fails exactly when the context is tight.
        Splitting the budget before retrieval runs makes the preference structural.
        """
        return int(self.token_budget * self.policy.code_share)

    async def build(
        self,
        section: dict,
        doc_type: str,
        semantic_limit: int = _RETRIEVAL_CANDIDATES,
    ) -> SectionContext:
        """
        Pack one section's context, filling toward the budget rather than to a constant.

        Measured on run 2, the old version left sections starved rather than trimmed:
        the opening section of an API document used 1,930 of 6,000 tokens — 32% — while
        44 module summaries and the rest of the index sat unused. Retrieval is now
        over-fetched once and admitted block by block until the budget is genuinely
        spent, and module summaries cover the files that were actually retrieved, not
        only the files the planner happened to name.
        """
        name = section.get("name") or "Section"
        focus = section.get("focus") or name
        key_files = [f for f in (section.get("key_files") or []) if f][:8]

        context = SectionContext(section_name=name, key_files=key_files)

        # 1. Narratives relevant to this document type — prior analysis, densest first.
        for narrative in await self._narratives_for(doc_type):
            context.narratives.append(narrative)

        # 2. Verbatim source for the planned files.
        for chunk in await self.store.get_by_paths(self.kb_id, key_files):
            context.source_blocks.append(self._format(chunk))

        # 3. One semantic lookup, over-fetched. Extra candidates cost a little DB time,
        #    not another embedding call, and give the fill step something to work with.
        candidates = await self._search_chunks(
            f"{name}. {focus}", limit=semantic_limit, exclude=key_files
        )

        # 4. Module summaries: the files the planner named *and* the files retrieval
        #    surfaced. These were paid for during analysis and are the cheapest context
        #    per token we own — scoping them to key files alone wasted most of them.
        related_paths = list(dict.fromkeys(key_files + [c.source_path for c in candidates]))
        modules = (
            await self.repos.modules.find_for_files(self.kb_id, related_paths)
            if related_paths
            else await self.repos.modules.list_by_kb(self.kb_id, limit=_MAX_MODULE_SUMMARIES)
        )
        for module in modules[:_MAX_MODULE_SUMMARIES]:
            if module.summary:
                context.module_summaries.append(
                    f"- **{module.name}** ({module.role}): {module.summary}"
                )

        # 5. Admit retrieved code while there is room for it — capped at the code
        #    share, so prose has somewhere to go when the policy allows it.
        self._fill(context, [self._format(c) for c in candidates], self.code_budget)

        # 6. Prose, only if this consumer is allowed it, and only from what the code
        #    share left behind. Retrieved separately rather than filtered out of one
        #    ranking: a shared ranking is exactly where prose out-competes code.
        if self.policy.allow_prose:
            prose = await self._search_chunks(
                f"{name}. {focus}", limit=_PROSE_CANDIDATES, chunk_types=PROSE_TYPES
            )
            # Its own allowance, added to whatever has been spent — *not* "everything
            # up to the total budget". Filling to the total would let prose expand
            # into the slack code did not use, so a section with thin source could
            # come back mostly unverified prose. The pools are fixed in both
            # directions: code cannot be crowded out, and prose cannot take more than
            # its share just because it was available.
            allowance = self.token_budget - self.code_budget
            ceiling = min(
                self.token_budget, count_text_tokens(context.render()) + allowance
            )
            self._fill(
                context,
                [self._format(c) for c in self._by_trust(prose)],
                ceiling,
                into="prose",
            )

        self._trim(context)
        return context

    def _fill(
        self,
        context: SectionContext,
        blocks: list[str],
        ceiling: int,
        into: str = "retrieved",
    ) -> None:
        """Add blocks one at a time, stopping at `ceiling` instead of at a count."""
        target = context.prose_blocks if into == "prose" else context.retrieved_blocks
        context.tokens = count_text_tokens(context.render())
        for block in blocks:
            projected = context.tokens + count_text_tokens(block)
            if projected > ceiling:
                break
            target.append(block)
            context.tokens = projected

    @staticmethod
    def _by_trust(chunks: list) -> list:
        """
        Docstrings before comments before markdown.

        A docstring ships in the same file as the code it describes and is reviewed
        in the same diff. A root README can be years older than everything it
        documents. Both are prose; they are not equally likely to be true.
        """
        order = {kind: index for index, kind in enumerate(PROSE_TRUST)}
        return sorted(chunks, key=lambda c: order.get(c.chunk_type, len(order)))

    async def search(
        self, query: str, limit: int = 6, exclude: list[str] | None = None
    ) -> list[str]:
        """
        One semantic lookup, formatted for a prompt.

        Also the write-time escape hatch: when a section's packed context turns out to
        be insufficient, the writer asks for exactly one more query through here.
        """
        return [self._format(c) for c in await self._search_chunks(query, limit, exclude)]

    async def _search_chunks(
        self,
        query: str,
        limit: int,
        exclude: list[str] | None = None,
        chunk_types: frozenset[str] | None = None,
    ) -> list:
        """
        Raw chunks, so callers can look at `source_path` before formatting.

        Defaults to code. Prose is never returned by accident: a caller that wants it
        has to name it, and the policy has to allow it.
        """
        embedding = await create_embedding(query)
        if embedding is None:
            return []
        wanted = chunk_types if chunk_types is not None else frozenset({CODE})
        if not self.policy.allow_prose:
            wanted = wanted & frozenset({CODE})
        if not wanted:
            return []
        return await self.store.search(
            project_id=self.project_id,
            query_embedding=embedding,
            limit=limit,
            kb_id=self.kb_id,
            exclude_paths=exclude or None,
            chunk_types=wanted,
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _narratives_for(self, doc_type: str) -> list[str]:
        """
        Narratives worth including, chosen by what is being written.

        Section context is the one place the token budget is genuinely contested, so
        this is the consumer that still truncates. Strategy and the planner take the
        full text.
        """
        out: list[str] = []
        for topic in topics_for_doc_type(doc_type):
            narrative = await self.repos.narratives.get(self.kb_id, topic)
            if narrative:
                out.append(f"### {topic}\n{narrative.content_md[:_NARRATIVE_CHARS_IN_SECTION]}")
        return out

    @staticmethod
    def _format(chunk) -> str:
        """
        One chunk, labelled with where it came from.

        Prose is marked in the block itself rather than only in the section heading,
        because blocks get reordered, truncated and quoted back — the label has to
        travel with the text. Code keeps its existing format exactly: every doc prompt
        in the system is built from it, and churning them buys nothing under a
        code-only policy.
        """
        location = f"{chunk.source_path}:{chunk.start_line}-{chunk.end_line}"
        if (chunk.chunk_type or CODE) in PROSE_TYPES:
            return f"--- {location} ({chunk.chunk_type}, unverified) ---\n{chunk.content}"
        return f"--- {location} ---\n```{chunk.language or ''}\n{chunk.content}\n```"

    def _trim(self, context: SectionContext) -> None:
        """
        Drop the least valuable material until the bundle fits.

        Order matters: semantically retrieved chunks go first because they are the
        least certain to be relevant; the planner's own key files go last.
        """
        context.tokens = count_text_tokens(context.render())
        while context.tokens > self.token_budget:
            if context.prose_blocks:
                # First to go, always. It is the least certain material in the bundle
                # and the only kind that can be actively misleading.
                context.prose_blocks.pop()
            elif context.retrieved_blocks:
                context.retrieved_blocks.pop()
            elif len(context.source_blocks) > 1:
                context.source_blocks.pop()
            elif context.narratives:
                context.narratives.pop()
            elif len(context.module_summaries) > 1:
                context.module_summaries.pop()
            else:
                break
            context.tokens = count_text_tokens(context.render())


__all__ = ["SectionContext", "SectionContextBuilder"]
