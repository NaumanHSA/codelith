"""
Deterministic extraction — the backbone of the knowledge base.

Opens the knowledge base for this commit and fills it with facts that need no LLM:
modules and their symbols, HTTP routes, dependencies, entrypoints, environment
variables and infrastructure. Because it is deterministic, everything here is
trustworthy enough for the QA stage to check generated prose against.
"""

from __future__ import annotations

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
