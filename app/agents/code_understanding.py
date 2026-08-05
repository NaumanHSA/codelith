import textwrap
from typing import Any

from app.agents.base import BaseAgent
from app.llm.client import create_embedding
from app.memory.graph_store import GraphStore
from app.memory.long_term import LongTermMemory
from app.memory.vector_store import VectorStore

_CHUNK_CHARS = 1500


class CodeUnderstandingAgent(BaseAgent):
    name = "code_understanding_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="CodeUnderstanding: embedding + graph build",
            end_message="CodeUnderstanding: complete",
        ) as t:
            await self._emit_log("info", "CodeUnderstanding: embedding code chunks into pgvector")
            await self._update_step(self.name, "running")

            project = state["project"]
            codebase = state.get("codebase")
            commit_sha: str | None = state.get("ingestion_result", {}).get("commit_sha")

            if not codebase or not codebase.files:
                await self._update_step(self.name, "completed", {"chunks_stored": 0})
                return {}

            # ── Long-term memory: skip re-embedding if same commit ─────────────
            ltm = LongTermMemory(self.db)
            if commit_sha:
                cached = await ltm.find_cached_job(project.id, commit_sha)
                if cached:
                    await self._emit_log(
                        "info",
                        f"Cache hit — skipping embedding (same commit {commit_sha[:8]} in job {cached.id})",
                    )
                    t.outputs(chunks_stored=0, cached=True)
                    await self._update_step(self.name, "completed", {"cached": True, "cached_job": cached.id})
                    # Return only what changed. Echoing the whole state re-applies it
                    # through the Annotated reducers (generated_docs uses operator.add),
                    # which silently doubles accumulated lists.
                    return {}

            # ── Embed into pgvector ────────────────────────────────────────────
            store = VectorStore(self.db)
            chunks_stored = embed_failures = 0

            for parsed_file in codebase.files:
                for chunk_text, start_line, end_line in self._split_into_chunks(parsed_file.content, parsed_file.path):
                    embedding = await create_embedding(chunk_text)
                    if embedding is None:
                        embed_failures += 1
                    await store.upsert(
                        project_id=project.id,
                        source_path=parsed_file.path,
                        content=chunk_text,
                        embedding=embedding or [],
                        chunk_type="code",
                        language=parsed_file.language,
                        start_line=start_line,
                        end_line=end_line,
                        job_id=self.job_id,
                    )
                    chunks_stored += 1

            await self.db.commit()
            await self._emit_log("info", "Chunks indexed", chunks=chunks_stored, embed_failures=embed_failures)

            # ── Build Neo4j code graph ─────────────────────────────────────────
            graph_stats: dict = {}
            try:
                async with GraphStore() as graph:
                    await graph.clear_project(project.id)
                    graph_stats = await graph.build_code_graph(project.id, codebase)
                await self._emit_log("info", "Graph built", **graph_stats)
            except Exception as exc:
                await self._emit_log("warning", f"Neo4j graph build failed (non-fatal): {exc}")

            # ── Record commit SHA for future cache hits ────────────────────────
            if commit_sha:
                await ltm.record_commit_sha(self.job_id, commit_sha)

            t.outputs(chunks_stored=chunks_stored, embed_failures=embed_failures, graph=graph_stats)
            await self._update_step(self.name, "completed", {
                "chunks_stored": chunks_stored,
                "embed_failures": embed_failures,
                "graph": graph_stats,
            })
            return {}

    def _split_into_chunks(self, content: str, path: str) -> list[tuple[str, int, int]]:
        lines = content.splitlines()
        chunks: list[tuple[str, int, int]] = []
        chunk_lines, overlap = 40, 5
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
