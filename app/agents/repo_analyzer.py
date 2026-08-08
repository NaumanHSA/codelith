import shutil
from pathlib import Path
from typing import Any

from app.agents.base import BaseAgent
from app.ingestion.pipeline import IngestionPipeline
from app.tracing.artifacts import save_artifact, save_input_artifact


class RepoAnalyzerAgent(BaseAgent):
    name = "repo_analyzer_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tracer = self._tracer()
        with tracer(
            kind="agent",
            agent_id=self.name,
            start_message="RepoAnalyzer: scanning project sources",
            end_message="RepoAnalyzer: complete",
        ) as t:
            await self._emit_log("info", "RepoAnalyzer: scanning project sources")
            await self._update_step(self.name, "running")

            project = state["project"]
            sandbox = state.get("sandbox")

            pipeline = IngestionPipeline(project=project, job_id=self.job_id, db=self.db)
            ingestion_result = await pipeline.run()

            codebase = getattr(pipeline, "_last_codebase", None)
            clone_path: Path | None = getattr(pipeline, "_last_clone_path", None)
            repo_path_str = str(clone_path) if clone_path else ""

            # Copy the source into the sandbox so MCP tools never touch the original repo.
            if sandbox and clone_path and clone_path.exists():
                try:
                    if sandbox.repo.is_symlink():
                        sandbox.repo.unlink()
                    elif sandbox.repo.exists():
                        shutil.rmtree(sandbox.repo)
                    shutil.copytree(
                        clone_path.resolve(),
                        sandbox.repo,
                        ignore=shutil.ignore_patterns(
                            ".git", "__pycache__", "*.pyc", "*.pyo",
                            "node_modules", ".venv", "venv", ".env",
                        ),
                        dirs_exist_ok=False,
                    )
                    repo_path_str = str(sandbox.repo)
                    await self._emit_log("info", "sandbox.repo copied", path=repo_path_str)
                except Exception as exc:
                    await self._emit_log("warning", f"Could not copy to sandbox.repo: {exc}")

            save_artifact("repo_analyzer.ingestion", ingestion_result)
            save_input_artifact(
                "repo_analyzer.files",
                [
                    {"path": f.path, "language": f.language, "chars": len(f.content)}
                    for f in (getattr(codebase, "files", None) or [])
                ],
            )

            t.outputs(
                sources=ingestion_result.get("sources_processed", 0),
                files=ingestion_result.get("total_files", 0),
                repo_path=repo_path_str,
            )
            await self._update_step(self.name, "completed", ingestion_result)
            await self._emit_log("info", "Sources analyzed", **ingestion_result)

            return {
                "ingestion_result": ingestion_result,
                "codebase": codebase,
                "repo_path": repo_path_str,
                "markdown_docs": getattr(pipeline, "_md_docs", []),
                "api_specs": getattr(pipeline, "_api_specs", []),
                "infra_context": getattr(pipeline, "_infra_context", []),
            }
