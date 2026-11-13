"""
Deterministic extraction — the backbone of the knowledge base.

Opens the knowledge base for this commit and fills it with facts that need no LLM:
modules and their symbols, HTTP routes, dependencies, entrypoints, environment
variables and infrastructure. Because it is deterministic, everything here is
trustworthy enough for the QA stage to check generated prose against.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from codelith.agents.base import BaseAgent
from codelith.config import get_settings
from codelith.db.repositories.knowledge import KnowledgeRepositories
from codelith.db.repositories.knowledge.source_repo import SnapshotFile
from codelith.ingestion.scratch import is_scratch_clone
from codelith.knowledge import incremental
from codelith.knowledge.builder import (
    SourceFile,
    build_modules,
    entities_from_api_specs,
    entities_from_infra,
    merge_entities,
    read_manifest_files,
)
from codelith.knowledge.churn import read as read_churn
from codelith.knowledge.detectors import detect_file_entities, read_project_files, scan_repository
from codelith.knowledge.history import read_commits
from codelith.llm.providers import embedding_spec
from codelith.tracing.artifacts import save_artifact


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

            # Config and infrastructure are invisible to the code parser: it only
            # yields files whose extension maps to a language, so `docker-compose.yml`,
            # `Dockerfile` and `.env.example` never reach it. Scanned from disk.
            file_entities: list[dict] = []
            if repo_path := state.get("repo_path"):
                file_entities = detect_file_entities(scan_repository(repo_path))

            entities = merge_entities(
                result.entities,
                file_entities,
                entities_from_api_specs(state.get("api_specs") or []),
                entities_from_infra(state.get("infra_context") or []),
            )

            await repos.modules.bulk_upsert(kb.id, result.modules)
            await repos.entities.bulk_add(kb.id, entities)

            # The files it takes to install and run the code: manifests, lockfiles,
            # env templates, containers, CI. Kept as files of the reading, a real
            # `.env` with its values masked before it reaches the database.
            project_files = await asyncio.to_thread(read_project_files, repo_path) if repo_path else []
            known = {f.path for f in files}
            kept = files + [
                SourceFile(path=p.path, content=p.content, language=p.language)
                for p in project_files
                if p.path not in known
            ]

            # Recorded here because this is the only stage holding file *content*.
            # Everything downstream sees paths; staleness needs to know what was in
            # them, so it can say which pages a commit actually invalidated.
            hashes = self._hashes(kept)
            await repos.bases.update(kb.id, file_hashes_json=hashes)

            # The reading's own copy of every file, each distinct content stored once,
            # so any file can be shown whole and any two readings compared line by line.
            project_by_path = {p.path: p for p in project_files}
            snapshot = await repos.sources.store(
                kb.id,
                [
                    SnapshotFile(
                        path=f.path,
                        content=f.content or "",
                        language=project_by_path[f.path].language if f.path in project_by_path else f.language,
                        kind=project_by_path[f.path].kind if f.path in project_by_path else None,
                        masked=project_by_path[f.path].masked if f.path in project_by_path else False,
                    )
                    for f in kept
                ],
            )
            await self.db.commit()
            await self._emit_log(
                "info",
                f"Kept {snapshot.files} file(s) of this reading, {len(project_files)} of them project files; "
                f"{snapshot.new_blobs} new, {snapshot.new_bytes // 1024} KB",
                files=snapshot.files,
                new_blobs=snapshot.new_blobs,
            )

            # Readings beyond the number kept give up their files; content none uses goes.
            if (keep := get_settings().KEEP_SOURCE_READINGS) > 0:
                pruned = await repos.sources.prune(project.id, keep)
                if pruned:
                    swept = await repos.sources.sweep()
                    await self.db.commit()
                    await self._emit_log("info", f"{pruned} older reading(s) gave up their files (KEEP_SOURCE_READINGS={keep}); {swept} unused blob(s) freed")

            # How often each file changed, while the checkout still exists to ask git.
            # More history is fetched only into a clone of ours, never a user's folder.
            if repo_path := state.get("repo_path"):
                churn = await asyncio.to_thread(
                    read_churn, repo_path, set(hashes), deepen=is_scratch_clone(Path(repo_path))
                )
                if churn is not None:
                    await repos.bases.update(kb.id, churn_json=churn.to_json())
                    await self.db.commit()
                    await self._emit_log(
                        "info",
                        f"Read {churn.commits} commit(s) of history: {churn.recent_commits} in the last {churn.days} days"
                        + (" (a shallow clone; history is partial)" if churn.shallow else ""),
                    )
                # The commits themselves, so two readings can list what came between them.
                try:
                    commits = await asyncio.to_thread(read_commits, repo_path)
                    if commits:
                        new = await repos.commits.store(project.id, commits)
                        await self.db.commit()
                        await self._emit_log("info", f"Kept {new} new commit(s) of the {len(commits)} read")
                except Exception as exc:  # noqa: BLE001 - history is extra; the reading stands without it
                    self.log.warning("commits_not_kept", error=f"{type(exc).__name__}: {exc}")

            # The same fingerprints decide what the rest of this reading may keep from
            # the last one. Facts above are always rebuilt: they need no model and are
            # what the comparison itself stands on.
            previous = await repos.bases.get_previous_reading(project.id, exclude_id=kb.id)
            reuse = incremental.plan(
                previous,
                hashes,
                force=bool(state.get("force")),
                embedding_model=embedding_spec().model,
            )
            if incremental.active(reuse):
                moved = len(incremental.touched(reuse))
                await self._emit_log(
                    "info",
                    f"Reading again since {(reuse.get('from_commit') or '')[:8] or 'the last reading'}: "
                    f"{moved} file(s) changed, {reuse['unchanged']} unchanged and kept",
                    changed=len(reuse["changed"]),
                    added=len(reuse["added"]),
                    removed=len(reuse["removed"]),
                )
            else:
                await self._emit_log("info", f"Reading everything: {reuse['reason']}")

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
                "reuse": reuse,
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
