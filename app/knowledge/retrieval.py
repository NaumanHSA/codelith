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
from app.llm.client import create_embedding
from app.llm.context_manager import count_text_tokens
from app.memory.vector_store import VectorStore


@dataclass(slots=True)
class SectionContext:
    """Everything handed to the model for one section, plus how it was obtained."""

    section_name: str
    module_summaries: list[str] = field(default_factory=list)
    narratives: list[str] = field(default_factory=list)
    source_blocks: list[str] = field(default_factory=list)
    retrieved_blocks: list[str] = field(default_factory=list)
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
    ) -> None:
        self.db = db
        self.kb_id = kb_id
        self.project_id = project_id
        self.token_budget = token_budget
        self.repos = KnowledgeRepositories.for_session(db)
        self.store = VectorStore(db)

    async def build(
        self,
        section: dict,
        doc_type: str,
        semantic_limit: int = 6,
    ) -> SectionContext:
        name = section.get("name") or "Section"
        focus = section.get("focus") or name
        key_files = [f for f in (section.get("key_files") or []) if f][:8]

        context = SectionContext(section_name=name, key_files=key_files)

        # 1. Modules that own the planned files — their summaries are the cheapest,
        #    densest context we have, and were paid for during analysis.
        modules = (
            await self.repos.modules.find_for_files(self.kb_id, key_files)
            if key_files
            else await self.repos.modules.list_by_kb(self.kb_id, limit=6)
        )
        for module in modules[:6]:
            if module.summary:
                context.module_summaries.append(
                    f"- **{module.name}** ({module.role}): {module.summary}"
                )

        # 2. Narratives relevant to this document type.
        for narrative in await self._narratives_for(doc_type):
            context.narratives.append(narrative)

        # 3. Verbatim source for the planned files.
        for chunk in await self.store.get_by_paths(self.kb_id, key_files):
            context.source_blocks.append(self._format(chunk))

        # 4. Semantic search to cover what the plan did not name.
        retrieved = await self.search(f"{name}. {focus}", limit=semantic_limit, exclude=key_files)
        context.retrieved_blocks.extend(retrieved)

        self._trim(context)
        return context

    async def search(
        self, query: str, limit: int = 6, exclude: list[str] | None = None
    ) -> list[str]:
        """
        One semantic lookup, formatted for a prompt.

        Also the write-time escape hatch: when a section's packed context turns out to
        be insufficient, the writer asks for exactly one more query through here.
        """
        embedding = await create_embedding(query)
        if embedding is None:
            return []
        chunks = await self.store.search(
            project_id=self.project_id,
            query_embedding=embedding,
            limit=limit,
            kb_id=self.kb_id,
            exclude_paths=exclude or None,
        )
        return [self._format(c) for c in chunks]

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _narratives_for(self, doc_type: str) -> list[str]:
        """Narratives worth including, chosen by what is being written."""
        from app.knowledge.constants import NarrativeTopic

        wanted: dict[str, tuple[NarrativeTopic, ...]] = {
            "architecture": (NarrativeTopic.ARCHITECTURE, NarrativeTopic.OVERVIEW),
            "api": (NarrativeTopic.REQUEST_LIFECYCLE, NarrativeTopic.AUTH),
            "deployment": (NarrativeTopic.DEPLOYMENT, NarrativeTopic.CONFIGURATION),
            "getting_started": (NarrativeTopic.OVERVIEW, NarrativeTopic.CONFIGURATION),
            "modules": (NarrativeTopic.ARCHITECTURE,),
        }.get(doc_type, (NarrativeTopic.OVERVIEW,))

        out: list[str] = []
        for topic in wanted:
            narrative = await self.repos.narratives.get(self.kb_id, topic)
            if narrative:
                out.append(f"### {topic}\n{narrative.content_md[:1500]}")
        return out

    @staticmethod
    def _format(chunk) -> str:
        location = f"{chunk.source_path}:{chunk.start_line}-{chunk.end_line}"
        language = chunk.language or ""
        return f"--- {location} ---\n```{language}\n{chunk.content}\n```"

    def _trim(self, context: SectionContext) -> None:
        """
        Drop the least valuable material until the bundle fits.

        Order matters: semantically retrieved chunks go first because they are the
        least certain to be relevant; the planner's own key files go last.
        """
        context.tokens = count_text_tokens(context.render())
        while context.tokens > self.token_budget:
            if context.retrieved_blocks:
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
