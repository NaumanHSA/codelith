import textwrap
from typing import Any

from app.agents.base import BaseAgent
from app.llm.client import create_embedding
from app.memory.vector_store import VectorStore

_CHUNK_CHARS = 1500  # target characters per chunk


class CodeUnderstandingAgent(BaseAgent):
    name = "code_understanding_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        await self._emit_log("info", "CodeUnderstanding: embedding code chunks into pgvector")
        await self._update_step(self.name, "running")

        project = state["project"]
        codebase = state.get("codebase")

        if not codebase or not codebase.files:
            await self._update_step(self.name, "completed", {"chunks_stored": 0})
            return state

        store = VectorStore(self.db)
        chunks_stored = 0
        embed_failures = 0

        for parsed_file in codebase.files:
            chunks = self._split_into_chunks(parsed_file.content, parsed_file.path)
            for chunk_text, start_line, end_line in chunks:
                embedding = await create_embedding(chunk_text)
                if embedding is None:
                    embed_failures += 1

                await store.upsert(
                    project_id=project.id,
                    source_path=parsed_file.path,
                    content=chunk_text,
                    embedding=embedding or [],  # store empty list when embedding fails
                    chunk_type="code",
                    language=parsed_file.language,
                    start_line=start_line,
                    end_line=end_line,
                    job_id=self.job_id,
                )
                chunks_stored += 1

        await self.db.commit()

        await self._update_step(self.name, "completed", {
            "chunks_stored": chunks_stored,
            "embed_failures": embed_failures,
        })
        await self._emit_log("info", "Chunks indexed", chunks=chunks_stored, embed_failures=embed_failures)

        return state

    def _split_into_chunks(
        self, content: str, path: str
    ) -> list[tuple[str, int, int]]:
        """Split file content into overlapping chunks by line count."""
        lines = content.splitlines()
        chunks: list[tuple[str, int, int]] = []
        chunk_lines = 40
        overlap = 5
        i = 0
        while i < len(lines):
            end = min(i + chunk_lines, len(lines))
            chunk_text = "\n".join(lines[i:end])
            if len(chunk_text) > _CHUNK_CHARS:
                chunk_text = textwrap.shorten(chunk_text, width=_CHUNK_CHARS, placeholder="...")
            chunks.append((chunk_text, i + 1, end))
            if end >= len(lines):
                break
            i += chunk_lines - overlap
        return chunks
