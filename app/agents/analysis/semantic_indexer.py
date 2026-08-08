"""
Semantic index — embeds the source into pgvector, scoped to this knowledge base.

Replaces the old `code_understanding` embedding loop, which issued one request and
one flush per chunk (about 1,476 sequential round-trips, ~30s on a real repo).
Chunks are now embedded in batches and inserted in one go.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.knowledge.builder import SourceFile, chunk_files, chunk_prose
from app.llm.client import create_embeddings
from app.memory.vector_store import VectorStore
from app.tracing.artifacts import save_artifact


class SemanticIndexerAgent(BaseAgent):
    name = "semantic_indexer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="SemanticIndexer: embedding source into pgvector",
            end_message="SemanticIndexer: complete",
        ) as t:
            await self._emit_log("info", "Embedding code chunks")
            await self._update_step(self.name, "running")

            project = state["project"]
            kb_id = state.get("kb_id")
            codebase = state.get("codebase")

            files = [
                SourceFile(path=f.path, content=f.content, language=f.language)
                for f in (getattr(codebase, "files", None) or [])
            ]
            chunks = chunk_files(files)

            # The repository's own prose, indexed alongside the code but tagged so a
            # retrieval policy can exclude it. Documentation generation never sees it —
            # writing a README back out as "generated documentation" is a failure that
            # looks like success. See `app/knowledge/policy.py`.
            prose = chunk_prose([
                SourceFile(path=d.path, content=d.content, language="markdown")
                for d in (state.get("markdown_docs") or [])
            ])
            if prose:
                await self._emit_log(
                    "info",
                    f"Indexing {len(prose)} prose chunk(s) from "
                    f"{len({p['source_path'] for p in prose})} markdown file(s)",
                )
            chunks.extend(prose)

            if not chunks:
                await self._update_step(self.name, "completed", {"chunks": 0})
                # Return an empty dict, never the state: `generated_docs`-style
                # accumulators would be re-applied by their reducer.
                return {"indexed_chunks": 0}

            embeddings = await create_embeddings([c["content"] for c in chunks])
            failures = sum(1 for e in embeddings if e is None)

            rows = [
                {
                    **chunk,
                    "project_id": project.id,
                    "job_id": self.job_id,
                    "kb_id": kb_id,
                    "embedding": embedding,
                }
                for chunk, embedding in zip(chunks, embeddings, strict=True)
                if embedding is not None
            ]
            stored = await VectorStore(self.db).bulk_add(rows)
            await self.db.commit()

            save_artifact(
                "semantic_indexer.chunks",
                {
                    "stored": stored,
                    "embed_failures": failures,
                    # Metadata only — the chunk text itself is already in Postgres.
                    "chunks": [
                        {
                            "path": c.get("source_path"),
                            "language": c.get("language"),
                            "start_line": c.get("start_line"),
                            "end_line": c.get("end_line"),
                            "chars": len(c.get("content") or ""),
                        }
                        for c in chunks
                    ],
                },
            )

            await self._emit_log(
                "info", f"Indexed {stored} chunks", chunks=stored, embed_failures=failures
            )
            t.outputs(chunks=stored, embed_failures=failures)
            await self._update_step(
                self.name, "completed", {"chunks": stored, "embed_failures": failures}
            )

            return {"indexed_chunks": stored, "embed_failures": failures}
