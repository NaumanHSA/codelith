"""
Deterministic extraction — the backbone of the knowledge base.

Opens the knowledge base for this commit and fills it with facts that need no LLM:
modules and their symbols, HTTP routes, dependencies, entrypoints, environment
variables and infrastructure. Because it is deterministic, everything here is
trustworthy enough for the QA stage to check generated prose against.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.agents.base import BaseAgent
from app.db.repositories.knowledge import KnowledgeRepositories
from app.knowledge.builder import (
    SourceFile,
    build_modules,
    entities_from_api_specs,
    entities_from_infra,
    merge_entities,
    read_manifest_files,
)
from app.tracing.artifacts import save_artifact


class StructuredExtractorAgent(BaseAgent):
    name = "structured_extractor_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="StructuredExtractor: building knowledge base facts",
            end_message="StructuredExtractor: complete",
        ) as t:
            await self._emit_log("info", "Extracting structural facts")
            await self._update_step(self.name, "running")

            project = state["project"]
            codebase = state.get("codebase")
            commit_sha = (state.get("ingestion_result") or {}).get("commit_sha")

            repos = KnowledgeRepositories.for_session(self.db)
            kb = await repos.bases.start_build(
                project_id=project.id, commit_sha=commit_sha, job_id=self.job_id
            )

            files = [
                SourceFile(path=f.path, content=f.content, language=f.language)
                for f in (getattr(codebase, "files", None) or [])
            ]
            # The code parser only yields files with a language extension, so manifests
            # are read separately — otherwise the KB records no dependencies at all.
            if repo_path := state.get("repo_path"):
                manifests = read_manifest_files(repo_path)
                if manifests:
                    await self._emit_log(
                        "info",
                        f"Read {len(manifests)} dependency manifest(s)",
                        files=[m.path for m in manifests],
                    )
                files.extend(manifests)

            result = build_modules(files)

            entities = merge_entities(
                result.entities,
                entities_from_api_specs(state.get("api_specs") or []),
                entities_from_infra(state.get("infra_context") or []),
            )

            await repos.modules.bulk_upsert(kb.id, result.modules)
            await repos.entities.bulk_add(kb.id, entities)
            # Recorded here because this is the only stage holding file *content*.
            # Everything downstream sees paths; staleness needs to know what was in
            # them, so it can say which pages a commit actually invalidated.
            await repos.bases.update(kb.id, file_hashes_json=self._hashes(files))
            await self.db.commit()

            save_artifact("structured_extractor.modules", result.modules)
            save_artifact("structured_extractor.entities", entities)

            stats = {**result.stats, "entities": len(entities)}
            await self._emit_log(
                "info",
                f"Extracted {len(result.modules)} modules and {len(entities)} facts",
                **stats,
            )
            t.outputs(kb_id=kb.id, **stats)
            await self._update_step(self.name, "completed", {"kb_id": kb.id, **stats})

            return {
                "kb_id": kb.id,
                "commit_sha": commit_sha,
                "extraction_stats": stats,
            }

    @staticmethod
    def _hashes(files: list[SourceFile]) -> dict[str, str]:
        """
        Content digest per file.

        Truncated to 16 hex characters: this is a change detector, not a security
        boundary, and a full digest per file triples the size of the column on a
        large repository for no gain.
        """
        return {
            f.path: hashlib.blake2b(
                (f.content or "").encode("utf-8", "replace"), digest_size=8
            ).hexdigest()
            for f in files
        }
