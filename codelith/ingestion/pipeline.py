from dataclasses import dataclass
from pathlib import Path
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.ingestion.repo.local import LocalRepoIngester
from codelith.ingestion.repo.github import GitHubRepoIngester
from codelith.ingestion.repo.gitlab import GitLabRepoIngester
from codelith.ingestion.repo.bitbucket import BitbucketRepoIngester
from codelith.ingestion.parsers.code_parser import CodeParser, ParsedCodebase
from codelith.ingestion.parsers.markdown_parser import MarkdownParser
from codelith.ingestion.parsers.openapi_parser import OpenApiParser, ParsedApiSpec
from codelith.ingestion.parsers.infra_parser import InfraParser, ParsedInfra

logger = structlog.get_logger(__name__)

_INGESTER_MAP = {
    "local": LocalRepoIngester,
    "github": GitHubRepoIngester,
    "gitlab": GitLabRepoIngester,
    "bitbucket": BitbucketRepoIngester,
}


@dataclass
class IngestionResult:
    sources_processed: int
    total_files: int
    languages: dict[str, int]
    markdown_files: int
    api_specs: int
    infra_files: int
    commit_sha: str | None
    errors: list[str]


class IngestionPipeline:
    def __init__(self, project, job_id: int, db: AsyncSession) -> None:
        self.project = project
        self.job_id = job_id
        self.db = db
        self.code_parser = CodeParser()
        self.md_parser = MarkdownParser()
        self.openapi_parser = OpenApiParser()
        self.infra_parser = InfraParser()
        self._last_codebase: ParsedCodebase | None = None
        self._last_clone_path: Path | None = None
        # Retained, not just counted: markdown is the repository's own prose, and
        # K3 indexes it as a router for questions. It was parsed and discarded.
        self._md_docs: list = []
        self._api_specs: list[ParsedApiSpec] = []
        self._infra_context: list[ParsedInfra] = []
        self._commit_sha: str | None = None

    async def run(self) -> dict:
        result = IngestionResult(
            sources_processed=0, total_files=0, languages={},
            markdown_files=0, api_specs=0, infra_files=0,
            commit_sha=None, errors=[],
        )

        for source in self.project.sources:
            try:
                logger.info("processing_source", source_type=source.source_type, path=source.url_or_path)
                await self._process_source(source, result)
                result.sources_processed += 1
            except Exception as exc:
                logger.error("source_error", source_id=source.id, error=str(exc))
                result.errors.append(f"Source {source.id}: {exc}")

        return {
            "sources_processed": result.sources_processed,
            "total_files": result.total_files,
            "languages": result.languages,
            "markdown_files": result.markdown_files,
            "api_specs": result.api_specs,
            "infra_files": result.infra_files,
            "commit_sha": result.commit_sha,
            "errors": result.errors,
        }

    async def _process_source(self, source, result: IngestionResult) -> None:
        ingester_cls = _INGESTER_MAP.get(source.source_type)
        if ingester_cls is None:
            logger.warning("unsupported_source_type", source_type=source.source_type)
            return

        clone_result = await ingester_cls().clone(source.url_or_path, branch=source.branch)
        root_path: Path = clone_result.local_path
        self._last_clone_path = root_path
        self._commit_sha = clone_result.commit_sha
        result.commit_sha = clone_result.commit_sha

        # ── Code ──────────────────────────────────────────────────────────────
        codebase: ParsedCodebase = self.code_parser.parse_directory(root_path)
        self._last_codebase = codebase
        result.total_files += codebase.total_files
        for lang, count in codebase.languages.items():
            result.languages[lang] = result.languages.get(lang, 0) + count

        # ── Markdown docs ──────────────────────────────────────────────────────
        md_docs = self.md_parser.parse_directory(root_path)
        self._md_docs.extend(md_docs)
        result.markdown_files += len(md_docs)

        # ── OpenAPI specs ──────────────────────────────────────────────────────
        api_specs = self.openapi_parser.parse_directory(root_path)
        self._api_specs.extend(api_specs)
        result.api_specs += len(api_specs)

        # ── Infrastructure files ───────────────────────────────────────────────
        infra = self.infra_parser.parse_directory(root_path)
        self._infra_context.extend(infra)
        result.infra_files += len(infra)

        logger.info(
            "source_parsed",
            files=codebase.total_files,
            languages=list(codebase.languages.keys()),
            md_files=len(md_docs),
            api_specs=len(api_specs),
            infra_files=len(infra),
        )
